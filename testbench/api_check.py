"""End-to-end API check of a running KARAG — every endpoint, every role.

Points at a live deployment (default http://10.10.10.25:3010, i.e. through the
console's /v1 proxy) and exercises each area with the right role *and* with
the wrong one: RBAC refusals are checked as carefully as successes. Everything
it creates is named ``qa-…`` and removed again at the end (tenants cannot be
deleted, so the one test tenant is suspended instead).

Model calls are real — a full run costs a few cents.

    KARAG_QA_URL=http://10.10.10.25:3010 \\
    KARAG_QA_TOKENS=path/to/tokens.txt \\
        PYTHONPATH=. .venv/bin/python testbench/api_check.py

``tokens.txt`` holds one ``user (role@tenant): token`` line per account (the
format the deployment step writes). Results: a table on stdout and
``testbench/build/api_check.json``.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BASE = os.environ.get("KARAG_QA_URL", "http://10.10.10.25:3010").rstrip("/")
TOKENS_FILE = os.environ.get("KARAG_QA_TOKENS", "")
RUN = uuid.uuid4().hex[:6]

results: list[dict] = []
cleanup: list = []


def load_tokens() -> dict[str, str]:
    out = {}
    for line in Path(TOKENS_FILE).read_text().splitlines():
        m = re.match(r"\s*\S+ \((\w+)@[\w-]+\): (\S+)", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


TOK = load_tokens()
client = httpx.Client(base_url=BASE, timeout=180)


def h(role: str | None) -> dict:
    return {"Authorization": f"Bearer {TOK[role]}"} if role else {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append({"check": name, "ok": bool(ok), "detail": detail[:300]})
    mark = "✓" if ok else "✗"
    print(f"  {mark} {name}" + (f" — {detail[:160]}" if detail and not ok else ""))
    return ok


def call(role, method, path, expect=200, name=None, **kw):
    r = client.request(method, path, headers=h(role), **kw)
    ok = r.status_code == expect if isinstance(expect, int) else r.status_code in expect
    body = r.text
    check(name or f"{role or 'anon'} {method} {path} → {expect}", ok,
          f"got {r.status_code}: {body[:200]}")
    try:
        return r, r.json()
    except Exception:
        return r, None


def section(title: str) -> None:
    print(f"\n== {title}")


# ------------------------------------------------------------------ files

def make_files() -> dict[str, tuple[str, bytes, str]]:
    sys.path.insert(0, str(ROOT.parent))
    from karag.office.docx import build_docx
    from karag.office.pptx import build_pptx
    from karag.office.xlsx import build_xlsx

    files = {
        "docx": ("qa-policy.docx", build_docx(
            title=f"QA политика возвратов {RUN}",
            paragraphs=["Возврат непродовольственных товаров возможен в течение 21 дня с чеком.",
                        "Лекарства надлежащего качества возврату не подлежат."]),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "xlsx": ("qa-prices.xlsx", build_xlsx({"Цены": [["Код", "Товар", "Цена"],
                                                         ["QA-777", "Тестовый сироп", "42,50"],
                                                         ["QA-778", "Тестовые капли", "17,00"]]}),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "pptx": ("qa-deck.pptx", build_pptx([{"title": "QA итоги", "bullets": ["Рост 12%", "План выполнен"]}]),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        "csv": ("qa-stock.csv", "товар;остаток\nQA сироп;5\n".encode(), "text/csv"),
        "md": ("qa-notes.md", f"# QA заметки {RUN}\n\n## Раздел\n\nКодовое слово: ЗЕЛЁНЫЙ-ДРАКОН-{RUN}.".encode(), "text/markdown"),
        "exe": ("qa-bad.exe", b"MZ\x90\x00", "application/octet-stream"),
    }
    scan = Path(os.environ.get("KARAG_QA_SCAN", ""))
    if scan.is_file():
        files["scan"] = ("qa-scan.pdf", scan.read_bytes(), "application/pdf")
    return files


def png_1x1() -> str:
    return ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ------------------------------------------------------------------ tests

def t_basics():
    section("health, identity, onboarding, language")
    r, j = call(None, "GET", "/health")
    check("health reports the configured model", j and "claude" in j.get("model", ""), str(j))
    call(None, "GET", "/v1/me", 401, "no token → 401")
    client.headers.pop("Authorization", None)
    r = client.get("/v1/me", headers={"Authorization": "Bearer not-a-token"})
    check("bad token → 401", r.status_code == 401, r.text)
    for role in TOK:
        r, j = call(role, "GET", "/v1/me", name=f"{role}: /v1/me")
        check(f"{role}: roles echo back", j and role in j.get("roles", []), str(j))
    call("employee", "GET", "/v1/onboarding", name="employee: onboarding guide")
    call("employee", "POST", "/v1/me/language", json={"language": "tg"}, name="employee: set language tg")
    call("employee", "POST", "/v1/me/language", json={"language": "xx"}, expect=(400, 422),
         name="employee: unknown language refused")
    call("employee", "POST", "/v1/me/language", json={"language": "auto"}, name="employee: language back to auto")


def t_tenants():
    section("tenants (platform operator)")
    call("admin", "GET", "/v1/tenants", 403, "tenant admin cannot list tenants")
    r, j = call("platform_admin", "GET", "/v1/tenants", name="ops lists tenants")
    ids = [t["id"] for t in (j or {}).get("tenants", [])]
    check("token-only tenant 'koinoti' visible to the operator", "koinoti" in ids,
          f"tenants={ids} — accounts from KARAG_TOKENS exist, but their tenant is not in the directory")
    tid = f"qa-{RUN}"
    call("platform_admin", "POST", "/v1/tenants", json={"id": tid, "name": "QA tenant"}, name="ops creates a tenant")
    call("admin", "POST", "/v1/tenants", 403, json={"id": "x" + tid, "name": "nope"}, name="admin cannot create a tenant")
    r, j = call("platform_admin", "PATCH", f"/v1/tenants/{tid}", json={"monthly_budget_usd": 5}, name="ops sets a budget")
    check("budget status returned", j and j.get("budget", {}).get("budget_usd") == 5, str(j))
    call("platform_admin", "PATCH", f"/v1/tenants/{tid}", json={"active": False}, name="ops suspends the QA tenant")
    call("platform_admin", "PATCH", "/v1/tenants/nope-nope", 404, json={"active": True}, name="unknown tenant → 404")


def t_accounts():
    section("accounts (tenant admin)")
    uid = f"qa-user-{RUN}"
    r, j = call("admin", "POST", "/v1/accounts", json={"user_id": uid, "display_name": "QA User", "roles": ["employee"]},
                name="admin creates an employee account")
    token = (j or {}).get("token")
    check("a one-time token is returned", bool(token), str(j)[:200])
    if token:
        r = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        check("the new token signs in", r.status_code == 200 and r.json().get("user_id") == uid, r.text)
    call("employee", "POST", "/v1/accounts", 403, json={"user_id": "qa-x", "roles": ["employee"]},
         name="employee cannot create accounts")
    call("admin", "POST", "/v1/accounts", 403, json={"user_id": f"qa-ops-{RUN}", "roles": ["platform_admin"]},
         name="admin cannot mint a platform_admin")
    call("admin", "POST", "/v1/accounts", expect=(400, 409, 422), json={"user_id": uid, "roles": ["employee"]},
         name="duplicate user id refused")
    r, j = call("admin", "GET", "/v1/accounts", name="admin lists accounts")
    check("list never contains token values", j and all("token" not in a for a in j.get("accounts", [])), str(j)[:200])
    call("admin", "PATCH", f"/v1/accounts/{uid}", json={"roles": ["employee", "hr"]}, name="admin changes roles")
    if token:
        r = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        check("role change applies on the next request", "hr" in r.json().get("roles", []), r.text)
    r, j = call("admin", "POST", f"/v1/accounts/{uid}/rotate", name="admin rotates the token")
    if token:
        r = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        check("old token dies after rotation", r.status_code == 401, r.text)
        token = (j or {}).get("token", token)
    call("admin", "PATCH", f"/v1/accounts/{uid}", json={"active": False}, name="admin suspends the account")
    r = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    check("suspended account is locked out", r.status_code in (401, 403), r.text)
    call("admin", "DELETE", f"/v1/accounts/{uid}", name="admin deletes the account")
    call("admin", "DELETE", f"/v1/accounts/{uid}", 404, name="deleting twice → 404")


def t_documents(files):
    section("documents (knowledge plane)")
    title = f"QA секретная премия {RUN}"
    r, j = call("admin", "POST", "/v1/ingest", json={"title": title, "text": f"Премия руководителя QA-{RUN}: 9999 сомони.", "data_class": "hr"},
                name="admin ingests an HR text document")
    hr_doc = (j or {}).get("document_id")
    call("employee", "POST", "/v1/ingest", 403, json={"title": "qa", "text": "x"}, name="employee cannot ingest")
    call("hr", "POST", "/v1/ingest", 403, json={"title": "qa", "text": "x", "data_class": "hr"},
         name="hr (no ingest role) cannot ingest")
    ids = {}
    for key in ("docx", "xlsx", "pptx", "csv", "md"):
        name, data, mime = files[key]
        r, j = call("admin", "POST", "/v1/ingest/file", files={"file": (f"{RUN}-{name}", data, mime)},
                    data={"data_class": "operational"}, name=f"admin uploads .{key}")
        ids[key] = (j or {}).get("document_id")
    name, data, mime = files["exe"]
    call("admin", "POST", "/v1/ingest/file", expect=(400, 415), files={"file": (name, data, mime)},
         data={"data_class": "operational"}, name="unsupported .exe refused")
    if "scan" in files:
        name, data, mime = files["scan"]
        r, j = call("admin", "POST", "/v1/ingest/file", files={"file": (f"{RUN}-{name}", data, mime)},
                    data={"data_class": "operational"}, name="scanned PDF is read (OCR)")
        ids["scan"] = (j or {}).get("document_id")
    r, j = call("admin", "POST", "/v1/documents/classify",
                files={"file": ("Зарплатная ведомость.txt", "Оклад и премия сотрудников за март.".encode(), "text/plain")},
                name="classification suggestion")
    check("payroll text suggested as hr", j and j.get("suggested") == "hr", str(j))
    r, j = call("admin", "POST", "/v1/documents/classify",
                files={"file": ("СОП холодовая цепь.txt",
                                "Стандартная операционная процедура: при отклонении температуры фармацевт "
                                "записывает это в журнал склада.".encode(), "text/plain")},
                name="classify an everyday SOP")
    check("an everyday SOP is not escalated to regulated", j and j.get("suggested") == "operational", str(j))
    r, j = call("admin", "POST", "/v1/ingest", json={"title": title, "text": "Премия: 1 сомони.", "data_class": "hr"},
                name="re-adding the same title replaces it")
    check("replaced list names the old document", j and hr_doc in (j.get("replaced") or []), str(j))
    hr_doc = (j or {}).get("document_id")
    r, j = call("employee", "GET", "/v1/documents", name="employee lists documents")
    titles = [d["title"] for d in (j or {}).get("documents", [])]
    check("employee does not see the HR title", title not in titles, str(titles)[:200])
    r, j = call("hr", "GET", "/v1/documents", name="hr lists documents")
    check("hr sees the HR title", title in [d["title"] for d in (j or {}).get("documents", [])])
    cleanup.extend(("admin", "DELETE", f"/v1/documents/{d}") for d in [hr_doc, *ids.values()] if d)
    call("employee", "DELETE", f"/v1/documents/{hr_doc}", expect=(403, 404), name="employee cannot delete")
    return ids


def t_ask():
    section("asking (knowledge plane through the model)")
    r, j = call("employee", "POST", "/v1/ask", json={"query": f"Какое кодовое слово в QA заметках {RUN}?"},
                name="employee asks about an uploaded document")
    text = (j or {}).get("text", "")
    check("answer contains the code word", f"ДРАКОН-{RUN}".lower() in text.lower().replace("ё", "е"), text[:200])
    check("answer cites a source", bool((j or {}).get("citations")), str((j or {}).get("citations"))[:200])
    r, j = call("employee", "POST", "/v1/ask", json={"query": f"Какая премия руководителя QA-{RUN}?"},
                name="employee asks about the HR document")
    check("no HR figure leaks to an employee", "9999" not in (j or {}).get("text", "") and "1 сомони" not in (j or {}).get("text", ""),
          (j or {}).get("text", "")[:200])
    r, j = call("hr", "POST", "/v1/ask", json={"query": f"Какая премия руководителя QA-{RUN}?"}, name="hr asks the same")
    check("hr gets the (replaced) figure", "1" in (j or {}).get("text", ""), (j or {}).get("text", "")[:200])
    r, j = call("employee", "POST", "/v1/ask", json={"query": "привет"}, name="small talk")
    check("small talk retrieves nothing", not (j or {}).get("citations"), str(j)[:200])
    call("employee", "POST", "/v1/ask", 400, json={"query": "   "}, name="empty question → 400")
    att = [{"kind": "file", "filename": "note.txt", "media_type": "text/plain",
            "data_b64": base64.b64encode("Номер заказа: QA-ORDER-555".encode()).decode()}]
    r, j = call("employee", "POST", "/v1/ask", json={"query": "Какой номер заказа в файле?", "attachments": att},
                name="question with an attached text file")
    check("answer uses the attachment", "555" in (j or {}).get("text", ""), (j or {}).get("text", "")[:200])
    img = [{"kind": "image", "filename": "dot.png", "media_type": "image/png", "data_b64": png_1x1()}]
    call("employee", "POST", "/v1/ask", json={"query": "Что на картинке?", "attachments": img}, name="question with an image")
    call("employee", "POST", "/v1/ask", 400, json={"query": "x", "attachments": [{"kind": "file", "filename": "a.txt", "data_b64": "!!!"}]},
         name="bad base64 → 400")
    call("employee", "POST", "/v1/ask", 415, json={"query": "x", "attachments": [{"kind": "image", "media_type": "image/bmp", "data_b64": png_1x1()}]},
         name="unsupported image type → 415")


def t_chats():
    section("chats (history, streaming)")
    r, j = call("employee", "POST", "/v1/chats", json={"title": "QA чат"}, name="create a chat")
    cid = (j or {}).get("id")
    if not cid:
        return
    cleanup.append(("employee", "DELETE", f"/v1/chats/{cid}"))
    r, j = call("employee", "POST", f"/v1/chats/{cid}/ask", json={"query": f"Сколько дней на возврат по QA политике возвратов {RUN}?"},
                name="ask inside a chat")
    check("chat answer mentions 21 days", "21" in (j or {}).get("answer", {}).get("text", json.dumps(j or {}, ensure_ascii=False)),
          json.dumps(j or {}, ensure_ascii=False)[:200])
    events = []
    with client.stream("POST", f"/v1/chats/{cid}/stream", headers={**h("employee"), "Accept": "text/event-stream"},
                       json={"query": "А лекарства можно вернуть?"}) as s:
        check("stream opens", s.status_code == 200, str(s.status_code))
        for line in s.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    kinds = [e["type"] for e in events]
    check("stream sends status, deltas, done", "delta" in kinds and kinds[-1] == "done", str(kinds[:12]))
    done = events[-1] if events else {}
    check("follow-up understood (medicines not returnable)", "не" in json.dumps(done, ensure_ascii=False), str(done)[:200])
    r, j = call("employee", "GET", f"/v1/chats/{cid}", name="read the chat back")
    check("history holds 4 messages", j and len(j.get("messages", [])) == 4, str(len((j or {}).get("messages", []))))
    call("employee", "PATCH", f"/v1/chats/{cid}", json={"title": "QA переименован"}, name="rename the chat")
    # a generated file is kept with the chat and survives a reload
    r, j = call("employee", "POST", f"/v1/chats/{cid}/ask",
                json={"query": "Сделай таблицу Excel: две колонки Аптека и Город, строки: №1 Душанбе, №2 Худжанд."},
                name="ask for a spreadsheet")
    arts = ((j or {}).get("answer") or {}).get("artifacts") or []
    check("an .xlsx came back", any(a.get("filename", "").endswith(".xlsx") for a in arts), str(arts)[:200])
    r, j = call("employee", "GET", f"/v1/chats/{cid}", name="history after the file")
    kept = [a for m in (j or {}).get("messages", []) for a in ((m.get("answer") or {}).get("artifacts") or [])]
    fid = next((a.get("file_id") for a in kept if a.get("file_id")), None)
    check("history keeps the file id", bool(fid), str(kept)[:200])
    if fid:
        r = client.get(f"/v1/chats/{cid}/files/{fid}", headers=h("employee"))
        check("saved file downloads after reload", r.status_code == 200 and r.content[:2] == b"PK", f"{r.status_code}")
        r = client.get(f"/v1/chats/{cid}/files/{fid}", headers=h("finance"))
        check("another user cannot download it", r.status_code == 404, f"{r.status_code}")
    call("finance", "GET", f"/v1/chats/{cid}", 404, name="another user cannot read it")
    call("finance", "DELETE", f"/v1/chats/{cid}", 404, name="another user cannot delete it")
    r, j = call("employee", "GET", "/v1/chats", name="list chats")
    check("renamed title listed", any(c["title"] == "QA переименован" for c in (j or {}).get("chats", [])))


def t_assistants():
    section("assistants")
    r, j = call("employee", "POST", "/v1/assistants", json={"name": f"QA помощник {RUN}", "instruction": "Отвечай очень кратко.",
                                                            "allowed_skill_names": []}, name="employee creates an assistant")
    aid = (j or {}).get("id")
    if not aid:
        return
    cleanup.append(("employee", "DELETE", f"/v1/assistants/{aid}"))
    call("employee", "GET", f"/v1/assistants/{aid}", name="read it")
    call("finance", "GET", f"/v1/assistants/{aid}", name="colleague can read/use it")
    call("finance", "PUT", f"/v1/assistants/{aid}", 403, json={"name": "hijack"}, name="colleague cannot edit it")
    call("employee", "PUT", f"/v1/assistants/{aid}", json={"instruction": "Отвечай одним словом."}, name="owner edits it")
    r, j = call("employee", "POST", f"/v1/assistants/{aid}/ask", json={"query": "Сколько дней действителен рецепт 107/у-НП?"},
                name="ask through the assistant")
    call("admin", "PUT", f"/v1/assistants/{aid}", json={"name": f"QA помощник {RUN} (admin)"}, name="admin may edit any assistant")
    call("employee", "DELETE", "/v1/assistants/nope", 404, name="unknown assistant → 404")


def t_data(files):
    section("data page: databases")
    db = ROOT / "build" / "apteka.db"
    dump = ROOT / "build" / "apteka_pg_dump.sql"
    call("employee", "GET", "/v1/connectors", 403, name="employee cannot see connections")
    cid = None
    if db.exists():
        r, j = call("admin", "POST", "/v1/databases/upload", files={"file": ("apteka.db", db.read_bytes(), "application/octet-stream")},
                    data={"name": f"QA Аптеки {RUN}", "data_class": "financial", "free_query": "true", "knowledge": "true", "language": "ru"},
                    name="admin uploads a SQLite database")
        cid = ((j or {}).get("connector") or {}).get("id")
        check("model described the database", bool(((j or {}).get("connector") or {}).get("metadata", {}).get("summary")), str(j)[:200])
    if cid:
        cleanup.append(("admin", "DELETE", f"/v1/databases/{cid}"))
        call("admin", "GET", f"/v1/databases/{cid}/schema", name="schema readback")
        call("admin", "PATCH", f"/v1/databases/{cid}", json={"table_classes": {"employees": "hr"}}, name="narrow employees to HR")
        r, j = call("finance", "POST", "/v1/ask", json={"query": "Какая аптека лучшая по выручке за весь период и сколько?"},
                    name="finance asks a data question")
        check("finance gets 313 594 via SQL", "313" in (j or {}).get("text", "") and bool((j or {}).get("queries_shown")),
              (j or {}).get("text", "")[:200])
        r, j = call("finance", "POST", "/v1/ask", json={"query": "Какой месячный фонд оплаты труда по таблице сотрудников?"},
                    name="finance asks about salaries")
        check("salaries stay closed to finance", "139" not in (j or {}).get("text", "").replace(" ", "")[:400],
              (j or {}).get("text", "")[:200])
        r, j = call("employee", "GET", "/v1/skills", name="employee skill list")
        check("employee is not offered the query skill", not any(s["name"].startswith("query_") for s in (j or {}).get("skills", [])))
        call("admin", "POST", f"/v1/databases/{cid}/describe", json={"comment": "суммы в сомони"}, name="re-describe with a comment")
    if dump.exists():
        r, j = call("admin", "POST", "/v1/databases/upload", files={"file": ("dump.sql", dump.read_bytes(), "application/sql")},
                    data={"name": f"QA дамп {RUN}", "data_class": "financial", "free_query": "false", "knowledge": "false", "language": "ru"},
                    name="admin imports a pg_dump")
        did = ((j or {}).get("connector") or {}).get("id")
        rep = ((j or {}).get("connector") or {}).get("metadata", {}).get("import", {})
        check("dump imported without failures", rep.get("failed_count") == 0 and rep.get("rows", 0) > 14000, str(rep)[:200])
        if did:
            cleanup.append(("admin", "DELETE", f"/v1/databases/{did}"))
    r, j = call("admin", "POST", "/v1/databases/test", expect=(400, 502), json={"kind": "sql_postgres", "host": "203.0.113.9", "port": 5432,
                                                                       "database": "x", "username": "x", "password": "x"},
                name="unreachable database → clear error")
    check("the error starts with a plain sentence", str((j or {}).get("detail", "")).startswith("The "),
          str(j)[:200])
    call("admin", "POST", "/v1/databases/upload", 400, files={"file": ("x.db", b"not sqlite", "application/octet-stream")},
         data={"name": "bad"}, name="a non-SQLite .db is refused")

    section("data page: API sources")
    url = "https://jsonplaceholder.typicode.com/users"
    r, j = call("admin", "POST", "/v1/sources/probe", json={"url": url, "language": "ru"}, name="probe a public API")
    check("probe found 10 records", j and (j.get("profile") or {}).get("record_count") == 10, str(j)[:200])
    for bad in ("http://127.0.0.1:8000/health", "http://169.254.169.254/latest/meta-data/", "http://api:8000/health",
                "file:///etc/passwd"):
        call("admin", "POST", "/v1/sources/probe", 400, json={"url": bad}, name=f"SSRF guard refuses {bad}")
    r, j = call("admin", "POST", "/v1/sources", json={"name": f"QA партнёры {RUN}", "url": url, "description": "пользователи",
                                                      "skill_enabled": True, "sync_enabled": True, "sync_interval_s": 600},
                name="save the API as skill + synced document")
    sid = (j or {}).get("id")
    if sid:
        cleanup.append(("admin", "DELETE", f"/v1/sources/{sid}"))
        call("admin", "POST", f"/v1/sources/{sid}/sync", name="sync now")
        call("admin", "PUT", f"/v1/sources/{sid}", json={"sync_enabled": False}, name="turn the sync off")


def t_skills():
    section("skills (authoring)")
    call("employee", "GET", "/v1/skills/definitions", 403, name="employee cannot author")
    r, j = call("admin", "POST", "/v1/connectors", expect=(200, 400, 403),
                json={"name": f"qa-appdb-{RUN}", "kind": "sql_sqlite", "config": {"path": "/data/karag_app.db"}},
                name="connector to the platform's own app DB")
    leak = r.status_code == 200
    check("platform's own database cannot be registered as a source", not leak,
          "an admin can point a connector at /data/karag_app.db (all tenants' accounts + audit)")
    if leak:
        conn_id = j["id"]
        cleanup.append(("admin", "DELETE", f"/v1/connectors/{conn_id}"))
        r, j = call("admin", "POST", "/v1/skills/definitions", expect=(200, 400),
                    json={"name": f"qa_leak_{RUN}", "description": "x", "connector_id": conn_id,
                          "sql": "SELECT tenant_id, id, roles FROM accounts LIMIT 5", "param_schema": {"type": "object", "properties": {}}},
                    name="skill over the app DB")
        if r.status_code == 200:
            cleanup.append(("admin", "DELETE", f"/v1/skills/definitions/{j['id']}"))
            r, j = call("admin", "POST", f"/v1/skills/definitions/{j['id']}/test", json={}, expect=(200, 400, 403, 500),
                        name="run it")
            check("no other tenant's accounts are readable", r.status_code != 200, r.text[:200])
    # a normal lookup over an uploaded DB
    r, j = call("admin", "GET", "/v1/connectors", name="list connections")
    sqlite_conn = next((c for c in (j or {}).get("connectors", []) if c["name"].startswith("QA Аптеки")), None)
    if sqlite_conn:
        r, j = call("admin", "POST", "/v1/skills/definitions", json={
            "name": f"qa_store_revenue_{RUN}", "description": "Выручка аптеки по id за период",
            "connector_id": sqlite_conn["id"], "required_data_class": "financial",
            "sql": "SELECT ROUND(SUM(amount),2) AS revenue FROM sales WHERE store_id = :store_id"},
            name="author a lookup skill (schema inferred)")
        sk = (j or {}).get("id")
        if sk:
            cleanup.append(("admin", "DELETE", f"/v1/skills/definitions/{sk}"))
            r, j = call("admin", "POST", f"/v1/skills/definitions/{sk}/test", json={"arguments": {"store_id": 1}}, name="test-run it")
            check("test run returns 313594.4", "313594" in json.dumps(j or {}), str(j)[:200])
            call("admin", "PUT", f"/v1/skills/definitions/{sk}", json={
                "name": f"qa_store_revenue_{RUN}", "description": "Выручка аптеки", "connector_id": sqlite_conn["id"],
                "sql": "SELECT ROUND(SUM(amount),2) AS revenue FROM sales WHERE store_id = :store_id",
                "required_data_class": "financial", "enabled": False}, name="disable it")
        call("admin", "POST", "/v1/skills/definitions", 400, json={
            "name": f"qa_bad_{RUN}", "description": "x", "connector_id": sqlite_conn["id"], "sql": "DELETE FROM sales"},
            name="write SQL refused at authoring")
    r, j = call("admin", "POST", "/v1/skills/definitions", json={
        "name": f"qa-procedure-{RUN}", "description": "Как оформить возврат", "kind": "agent",
        "instructions": "1. Проверить чек. 2. Оформить акт.", "required_data_class": "operational"},
        name="author a procedure (SKILL.md)")
    pid = (j or {}).get("id")
    if pid:
        cleanup.append(("admin", "DELETE", f"/v1/skills/definitions/{pid}"))
        r = client.get(f"/v1/skills/definitions/{pid}/skill_md", headers=h("admin"))
        check("SKILL.md export", r.status_code == 200 and "name:" in r.text, r.text[:120])
        call("admin", "POST", "/v1/skills/parse_skill_md", json={"text": r.text}, name="SKILL.md parse round-trip")
    call("admin", "GET", "/v1/skills/library", name="shared library")


def t_alerts():
    section("alerts")
    call("employee", "POST", "/v1/alerts", 403, json={"name": "x", "skill_name": "x"}, name="employee cannot create alerts")
    r, j = call("ceo", "GET", "/v1/skills", name="ceo skills")
    sk = (j or {}).get("skills", [])
    check("skills carry a category", all("category" in s for s in sk), str(sk[:1])[:200])
    call("ceo", "POST", "/v1/alerts", 400, json={"name": "x", "skill_name": "create_spreadsheet"},
         name="an alert cannot run a file maker")
    call("ceo", "POST", "/v1/alerts", 400, json={"name": "x", "skill_name": "no_such_lookup"},
         name="an alert cannot name an unknown lookup")
    q = next((s["name"] for s in sk if s["name"].startswith("query_qa")), None)
    if not q:
        check("a query skill exists for the alert test", False, "upload step failed")
        return
    r, j = call("ceo", "POST", "/v1/alerts", json={
        "name": f"QA дефицит {RUN}", "skill_name": q, "arguments": {"sql": "SELECT COUNT(*) AS n FROM stock WHERE on_hand < reorder_at"},
        "condition": "field_compare", "condition_config": {"field": "n", "op": ">", "value": 0},
        "message_template": "Позиций ниже порога: {n}", "interval_s": 3600}, name="ceo creates an alert")
    aid = (j or {}).get("id")
    if aid:
        cleanup.append(("ceo", "DELETE", f"/v1/alerts/{aid}"))
        r, j = call("ceo", "POST", f"/v1/alerts/{aid}/run", name="run it now")
        check("alert fired with 39", "39" in json.dumps(j or {}, ensure_ascii=False), json.dumps(j or {}, ensure_ascii=False)[:200])
        call("ceo", "PATCH", f"/v1/alerts/{aid}", json={"enabled": False}, name="pause it")


def t_audit_usage():
    section("audit, usage, budget")
    call("employee", "GET", "/v1/audit", 403, name="employee cannot read the audit")
    r, j = call("admin", "GET", "/v1/audit", name="admin reads the audit")
    ev = (j or {}).get("events", [])
    check("audit rows carry ip + roles", ev and ev[0].get("ip") and ev[0].get("roles"), str(ev[:1])[:200])
    r, j = call("ceo", "GET", "/v1/usage", name="usage")
    check("usage priced, budget block present", j and j.get("cost_usd", 0) > 0 and "budget" in j, str(j)[:200])


def t_engineer_and_webhooks():
    section("engineering, webhooks")
    call("employee", "GET", "/v1/code/proposals", 403, name="employee cannot see proposals")
    call("karag_engineer", "GET", "/v1/code/proposals", name="engineer lists proposals")
    r = client.post("/v1/webhooks/telegram", json={"update_id": 1, "message": {"message_id": 1, "chat": {"id": 42}, "from": {"id": 42},
                                                                                 "text": "покажи зарплаты"}})
    check("telegram: unknown sender refused, nothing runs", r.status_code == 200 and "зарплат" not in r.text, r.text[:200])
    r = client.get("/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"})
    check("whatsapp: wrong verify token refused", r.status_code in (403, 404), f"{r.status_code} {r.text[:100]}")


def t_rate_limit():
    section("rate limit")
    codes = []
    for _ in range(32):
        r = client.post("/v1/ask", headers=h("hr"), json={"query": "ок"})
        codes.append(r.status_code)
        if r.status_code == 429:
            check("429 carries Retry-After", "retry-after" in {k.lower() for k in r.headers}, str(dict(r.headers)))
            break
    check("rate limit trips within 31 questions", 429 in codes, str(codes))


def main() -> None:
    files = make_files()
    started = time.time()
    try:
        t_basics()
        t_tenants()
        t_accounts()
        t_documents(files)
        t_ask()
        t_chats()
        t_assistants()
        t_data(files)
        t_skills()
        t_alerts()
        t_audit_usage()
        t_engineer_and_webhooks()
        if os.environ.get("KARAG_QA_RATE_LIMIT") == "1":
            t_rate_limit()
    finally:
        section("cleanup")
        for role, method, path in reversed(cleanup):
            r = client.request(method, path, headers=h(role))
            print(f"  {method} {path} → {r.status_code}")
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed in {time.time() - started:.0f}s")
    for r in failed:
        print(f"  ✗ {r['check']}: {r['detail'][:220]}")
    out = ROOT / "build" / "api_check.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
