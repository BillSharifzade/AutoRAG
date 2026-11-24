"""Drive the console in a real browser, because curl proves nothing about the UI.

The API can be perfect while a page is broken, so this walks what a tester walks
— signs in, runs the API wizard, connects a database from its login form, drops
a dump file, asks a question in chat, switches language, and looks at every page
as a restricted user — writing a screenshot per step.

    .venv/bin/python testbench/ui_check.py                 # every flow
    .venv/bin/python testbench/ui_check.py --flow db,i18n  # only some
    .venv/bin/python testbench/ui_check.py --port 3100     # a scratch console

Flows: api, db, upload, chat, i18n, employee, pages.

Two traps this script exists to avoid:

* **``localhost``, never ``127.0.0.1``.** Next blocks cross-origin requests to
  ``/_next/*`` from the IP form, so the chunks never load and the page renders
  as an empty body with no error — it looks exactly like a broken app.
* Signing in by typing is brittle; the token goes straight into localStorage.

The Hyperspeed WebGL background throws ``EffectComposer.addPass … 'alpha'`` under
software rendering. That is headless-only noise, not a page error.

The database password used here is the throwaway ``karag_reader`` login that
``testbench/up.sh`` created for a disposable container — nothing real.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    import websockets
except ModuleNotFoundError:  # pragma: no cover
    sys.exit("websockets is missing: .venv/bin/pip install websockets")

ROOT = pathlib.Path(__file__).parent
SHOTS = ROOT / "build" / "ui"
ALL_FLOWS = ("api", "db", "upload", "chat", "i18n", "employee", "pages")


class Browser:
    """The handful of CDP calls this needs, and nothing else."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._id = 0

    async def call(self, method: str, **params) -> dict:
        self._id += 1
        await self._ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(await self._ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, expression: str):
        out = await self.call("Runtime.evaluate", expression=expression,
                              awaitPromise=True, returnByValue=True)
        if out.get("exceptionDetails"):
            raise RuntimeError(out["exceptionDetails"].get("text", "js failed"))
        return out.get("result", {}).get("value")

    async def goto(self, url: str, settle: float = 3.0) -> None:
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(settle)

    async def shot(self, name: str) -> pathlib.Path:
        """Full-page: override the viewport to the measured height, then clear it."""
        height = await self.js("document.documentElement.scrollHeight")
        await self.call("Emulation.setDeviceMetricsOverride", width=1440,
                        height=min(int(height) + 40, 4000), deviceScaleFactor=1, mobile=False)
        data = await self.call("Page.captureScreenshot", format="png")
        await self.call("Emulation.clearDeviceMetricsOverride")
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"{name}.png"
        path.write_bytes(base64.b64decode(data["data"]))
        return path

    async def click_text(self, text: str, *, exact: bool = False) -> bool:
        """Click a button/link by its visible text.

        ``exact`` matters more than it looks: a step header and the footer's
        submit button can both read "Сохранить", and clicking the header only
        folds the step away.
        """
        return bool(await self.js(f"""(() => {{
            const want = {json.dumps(text)}.toLowerCase();
            const exact = {json.dumps(exact)};
            const el = [...document.querySelectorAll('button, a, [role=button], [role=radio]')]
                .filter(e => {{
                    const t = (e.innerText || '').trim().toLowerCase();
                    return exact ? t === want : t.includes(want);
                }})
                .filter(e => e.offsetParent !== null && !e.disabled)
                .pop();
            if (!el) return false;
            el.scrollIntoView({{block: 'center'}});
            el.click();
            return true;
        }})()"""))

    async def _set_value(self, finder: str, value: str) -> bool:
        """Type into a React-controlled field: the native setter, then an event."""
        return bool(await self.js(f"""(() => {{
            const el = {finder};
            if (!el) return false;
            const proto = el.tagName === 'TEXTAREA'
                ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, {json.dumps(value)});
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            return true;
        }})()"""))

    async def fill(self, selector: str, value: str) -> bool:
        return await self._set_value(f"document.querySelector({json.dumps(selector)})", value)

    async def fill_label(self, label: str, value: str) -> bool:
        """Fill the input under a <Field label=…> — the label is a span, not a <label>."""
        finder = f"""(() => {{
            const want = {json.dumps(label)}.trim().toLowerCase();
            const span = [...document.querySelectorAll('span')]
                .find(s => (s.textContent || '').trim().toLowerCase() === want);
            if (!span) return null;
            const box = span.parentElement && span.parentElement.parentElement;
            return box ? box.querySelector('input, textarea') : null;
        }})()"""
        return await self._set_value(finder, value)

    async def set_file(self, selector: str, path: pathlib.Path) -> bool:
        """Hand a file to a hidden <input type=file> the way a chooser would."""
        doc = await self.call("DOM.getDocument")
        found = await self.call("DOM.querySelector", nodeId=doc["root"]["nodeId"],
                                selector=selector)
        node = found.get("nodeId")
        if not node:
            return False
        await self.call("DOM.setFileInputFiles", files=[str(path.resolve())], nodeId=node)
        return True

    async def text(self) -> str:
        return await self.js("document.body.innerText") or ""

    async def wait_for(self, needle: str, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle.lower() in (await self.text()).lower():
                return True
            await asyncio.sleep(1)
        return False

    async def sign_in(self, base: str, token: str) -> None:
        await self.goto(f"{base}/", settle=2)
        await self.js(f"localStorage.setItem('karag_token', {json.dumps(token)})")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes = 0

    def check(self, ok: bool, label: str) -> bool:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}", flush=True)
        if ok:
            self.passes += 1
        else:
            self.failures.append(label)
        return ok


# --------------------------------------------------------------------------
# flows


async def flow_api(b: Browser, base: str, r: Report, url: str) -> None:
    print("▸ API wizard")
    await b.goto(f"{base}/data", settle=4)
    body = await b.text()
    r.check("Данные" in body or "Data" in body, "/data renders")
    r.check("Остатки аптек" in body, "API sources are listed")
    r.check("Аптеки PG" in body or "Аптеки MySQL" in body, "databases are listed")
    r.check("каждые 0 ч" not in body and "every 0 h" not in body,
            "a sub-hour refresh reads in minutes, not '0 h'")
    await b.shot("01-data-list")

    r.check(await b.click_text("Подключить API") or await b.click_text("Connect an API"),
            "the API wizard opens")
    await asyncio.sleep(1.5)
    r.check(await b.fill("input[placeholder*='erp.company.com']", url),
            "the URL field accepts input")
    r.check(await b.click_text("Получить") or await b.click_text("Fetch"),
            "'fetch and read' is clickable")
    # "Что пришло" is the collapsed step's own title, so it says nothing about
    # the fetch: wait for content only the finished probe renders.
    r.check(await b.wait_for("Как понял помощник", 120)
            or await b.wait_for("What the assistant understood", 5),
            "the endpoint is read and the description comes back")
    await asyncio.sleep(1)
    await b.shot("02-api-wizard-review")
    page = await b.text()
    r.check("записей" in page or "records" in page, "the record count is reported")
    r.check(any(w in page.lower() for w in ("аптек", "препарат", "товар", "каталог")),
            "the assistant describes the data in Russian")
    r.check(await b.click_text("Далее") or await b.click_text("Next"),
            "the review step continues to save")
    await asyncio.sleep(1)
    r.check(await b.click_text("Сохранить", exact=True) or await b.click_text("Save", exact=True),
            "save is clickable")
    r.check(await b.wait_for("Подключено", 60) or await b.wait_for("Connected", 5),
            "the source is saved and the page says so")
    await asyncio.sleep(2)
    await b.shot("03-api-wizard-saved")


async def flow_db(b: Browser, base: str, r: Report) -> None:
    print("▸ database wizard, from the login form")
    await b.goto(f"{base}/data", settle=3)
    r.check(await b.click_text("Подключить базу") or await b.click_text("Connect a database"),
            "the database wizard opens")
    await asyncio.sleep(1.5)
    r.check(await b.click_text("MySQL"), "MySQL can be chosen")
    await asyncio.sleep(0.5)
    filled = all([
        await b.fill_label("Хост", "karag-test-mysql"),
        await b.fill_label("Порт", "3306"),
        await b.fill_label("База", "apteka"),
        await b.fill_label("Пользователь", "karag_reader"),
        await b.fill_label("Пароль", "readonly"),
    ])
    r.check(filled, "the login form accepts host/port/database/user/password")
    await b.shot("04-db-wizard-login")
    r.check(await b.click_text("Проверить подключение") or await b.click_text("Check connection"),
            "'check connection' is clickable")
    r.check(await b.wait_for("таблиц", 60) or await b.wait_for("tables", 5),
            "the connection check reports the tables it found")
    await b.fill_label("Название", "Аптеки MySQL из браузера")
    r.check(await b.click_text("Прочитать и описать") or await b.click_text("Read and describe"),
            "'read and describe' is clickable")
    r.check(await b.wait_for("sales", 180), "the schema comes back described")
    await asyncio.sleep(1)
    await b.shot("05-db-wizard-described")
    r.check(await b.click_text("Готово", exact=True) or await b.click_text("Done", exact=True),
            "the wizard finishes")
    await asyncio.sleep(3)
    r.check("Аптеки MySQL из браузера" in await b.text(),
            "the new connection is on the page")
    await b.shot("06-db-connected")


async def flow_upload(b: Browser, base: str, r: Report) -> None:
    print("▸ database wizard, dropping a dump file")
    dump = ROOT / "build" / "apteka_mysql_dump.sql"
    if not dump.exists():
        r.check(False, "the dump fixture exists (run testbench/up.sh)")
        return
    await b.goto(f"{base}/data", settle=3)
    await b.click_text("Подключить базу") or await b.click_text("Connect a database")
    await asyncio.sleep(1.5)
    r.check(await b.click_text("Загрузить файл") or await b.click_text("Upload a file"),
            "the file option can be chosen")
    await asyncio.sleep(0.5)
    r.check(await b.set_file("input[type=file]", dump), "a file can be handed to the chooser")
    await asyncio.sleep(1)
    r.check(dump.name in await b.text(), "the chosen file is shown back")
    await b.fill_label("Название", "Дамп через браузер")
    await b.shot("07-db-wizard-file")
    r.check(await b.click_text("Прочитать и описать") or await b.click_text("Read and describe"),
            "'read and describe' is clickable")
    r.check(await b.wait_for("sales", 240), "the imported dump is described")
    r.check(await b.click_text("Готово", exact=True) or await b.click_text("Done", exact=True),
            "the wizard finishes")
    await asyncio.sleep(3)
    r.check("Дамп через браузер" in await b.text(), "the imported database is on the page")
    await b.shot("08-db-imported")


async def flow_chat(b: Browser, base: str, r: Report) -> None:
    print("▸ chat, in the browser")
    await b.goto(f"{base}/", settle=4)
    r.check(await b.fill("textarea", "Сколько позиций сейчас ниже порога дозаказа?"),
            "the composer accepts a question")
    await b.js("""(() => {
        const t = document.querySelector('textarea');
        t.dispatchEvent(new KeyboardEvent('keydown',
            {key: 'Enter', code: 'Enter', bubbles: true}));
    })()""")
    r.check(await b.wait_for("39", 180), "the answer streams back with the right number")
    await asyncio.sleep(1)
    await b.shot("09-chat-answer")
    page = await b.text()
    r.check("Остатки" in page or "fetch" in page.lower() or "источник" in page.lower(),
            "the answer shows where the number came from")


async def flow_i18n(b: Browser, base: str, r: Report) -> None:
    print("▸ language switch")
    await b.goto(f"{base}/data", settle=3)
    r.check(await b.click_text("EN", exact=True), "EN is clickable")
    await asyncio.sleep(2)
    en = await b.text()
    r.check("Connect your data" in en or "Connect an API" in en, "the page switches to English")
    await b.shot("10-english")
    r.check(await b.click_text("RU", exact=True), "RU is clickable")
    await asyncio.sleep(2)
    r.check("Подключите свои данные" in await b.text(), "and back to Russian")


async def flow_employee(b: Browser, base: str, r: Report, token: str) -> None:
    print("▸ what an employee sees")
    await b.sign_in(base, token)
    await b.goto(f"{base}/data", settle=4)
    page = await b.text()
    r.check("Аптеки PG" not in page and "karag-test-pg" not in page,
            "the Data page hides the connections from an employee")
    r.check("данные подключают" in page.lower() or "administrators connect data" in page.lower(),
            "the Data page explains the restriction in its own words, not the Skills page's")
    await b.shot("11-employee-data")
    await b.goto(f"{base}/skills", settle=3)
    skills = await b.text()
    r.check("Revenue by store" not in skills,
            "a management-only skill is not listed for an employee")
    await b.shot("12-employee-skills")
    await b.goto(f"{base}/", settle=3)
    r.check(await b.fill("textarea", "Какой оклад у заведующей Аптеки №1?"),
            "an employee can still ask a question")
    await b.js("""(() => {
        const t = document.querySelector('textarea');
        t.dispatchEvent(new KeyboardEvent('keydown',
            {key: 'Enter', code: 'Enter', bubbles: true}));
    })()""")
    got = await b.wait_for("не могу", 180) or await b.wait_for("нет прав", 5)
    r.check(got, "and is refused the salary, in words")
    await b.shot("13-employee-refused")


async def flow_pages(b: Browser, base: str, r: Report) -> None:
    print("▸ the rest of the console")
    for path, name in (("/assistants", "14-assistants"), ("/documents", "15-documents"),
                       ("/usage", "16-usage"), ("/audit", "17-audit")):
        await b.goto(f"{base}{path}", settle=3)
        text = await b.text()
        r.check(len(text.strip()) > 60, f"{path} renders")
        r.check("Application error" not in text and "Unhandled" not in text,
                f"{path} has no error boundary showing")
        await b.shot(name)
    # the Documents page has to accept a file, not just render — and its file
    # input only exists once "upload" is chosen over "write it"
    doc = ROOT / "build" / "schema_notes.md"
    await b.goto(f"{base}/documents", settle=3)
    r.check(await b.click_text("Загрузить файл") or await b.click_text("Upload a file"),
            "the Documents page offers a file upload")
    await asyncio.sleep(1)
    if doc.exists() and await b.set_file("input[type=file]", doc):
        await asyncio.sleep(3)
        r.check("schema_notes" in await b.text() or "Справка" in await b.text(),
                "a document uploaded from the browser appears")
        await b.shot("18-document-uploaded")
    else:
        r.check(False, "the Documents page exposes a file input")


# --------------------------------------------------------------------------


def launch(port: int) -> tuple[subprocess.Popen, str, str]:
    binary = next((b for b in ("google-chrome-stable", "google-chrome", "chromium")
                   if shutil.which(b)), None)
    if binary is None:
        sys.exit("no chrome on PATH")
    profile = tempfile.mkdtemp(prefix="karag-ui-")
    proc = subprocess.Popen(
        [binary, "--headless=new", "--no-sandbox", "--enable-unsafe-swiftshader",
         "--disable-gpu", "--window-size=1440,900",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/json/list", timeout=1) as resp:
                tabs = json.load(resp)
            page = next(t for t in tabs if t["type"] == "page")
            return proc, page["webSocketDebuggerUrl"], profile
        except Exception:
            time.sleep(0.5)
    proc.kill()
    sys.exit("chrome did not come up")


async def run(base: str, token: str, emp_token: str, url: str, flows: list[str]) -> int:
    proc, ws_url, profile = launch(9333)
    r = Report()
    try:
        async with websockets.connect(ws_url, max_size=60_000_000) as ws:
            b = Browser(ws)
            await b.call("Page.enable")
            await b.call("Runtime.enable")
            await b.sign_in(base, token)

            if "api" in flows:
                await flow_api(b, base, r, url)
            if "db" in flows:
                await flow_db(b, base, r)
            if "upload" in flows:
                await flow_upload(b, base, r)
            if "chat" in flows:
                await flow_chat(b, base, r)
            if "i18n" in flows:
                await flow_i18n(b, base, r)
            if "pages" in flows:
                await flow_pages(b, base, r)
            if "employee" in flows:
                await flow_employee(b, base, r, emp_token)
    finally:
        proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    print(f"\n{r.passes} passed, {len(r.failures)} failed"
          + ("".join(f"\n  ✗ {f}" for f in r.failures) if r.failures else ""))
    print(f"screenshots in {SHOTS}")
    return 1 if r.failures else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3000)
    ap.add_argument("--token", default="tkn_ceo")
    ap.add_argument("--employee-token", default="tkn_emp")
    ap.add_argument("--flow", default="all", help=f"comma-separated: {', '.join(ALL_FLOWS)}")
    ap.add_argument("--url", default="http://karag-test-api:8100/v1/products",
                    help="endpoint to run through the API wizard")
    a = ap.parse_args()
    flows = list(ALL_FLOWS) if a.flow == "all" else [f.strip() for f in a.flow.split(",")]
    raise SystemExit(asyncio.run(
        run(f"http://localhost:{a.port}", a.token, a.employee_token, a.url, flows)))


if __name__ == "__main__":
    main()
