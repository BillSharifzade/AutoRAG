"""Answer-quality evaluation for KARAG.

Runs ``evals/questions.json`` against ``evals/corpus/`` (plus the testbench
pharmacy database as a free-query skill) on an isolated, in-memory platform —
the real instance and its data are never touched — and scores every answer:

* **facts**    — the expected facts appear in the answer (numbers normalised:
                 "4 200" = "4200", "27,4" = "27.4")
* **leaks**    — a caller without clearance never sees the protected figure
* **abstain**  — "not in the documents" questions are answered as such
* **retrieval**— a passage from the right document reached the model
* **citations**— every cited source is one of the right documents

Usage (needs the provider keys in the environment; embeddings are cached in
``evals/.cache`` so repeated runs only pay for generation):

    set -a; source .env; set +a
    PYTHONPATH=. .venv/bin/python evals/run_eval.py --label baseline
    PYTHONPATH=. .venv/bin/python evals/run_eval.py --model claude-sonnet-5-5 --effort low
    PYTHONPATH=. .venv/bin/python evals/run_eval.py --retrieval-only     # no model calls
    PYTHONPATH=. .venv/bin/python evals/run_eval.py --only code-amk,leak-salary

Results land in ``evals/results/<timestamp>-<label>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))

from karag.config import Settings  # noqa: E402
from karag.domain import DataClass, Principal  # noqa: E402
from karag.factory import build_platform  # noqa: E402
from karag.llm.base import ChatMessage, MsgRole  # noqa: E402
from karag.pricing import PriceList  # noqa: E402
from karag.usage import billable_input_tokens  # noqa: E402

TENANT = "koinoti"
DB_PATH = REPO / "testbench" / "build" / "apteka.db"


# ------------------------------------------------------------------ corpus

def load_corpus() -> list[dict]:
    docs = []
    for path in sorted((ROOT / "corpus").glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta: dict = {}
        if raw.startswith("---"):
            head, raw = raw[3:].split("---", 1)
            for line in head.strip().splitlines():
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        docs.append({
            "key": path.stem,
            "title": meta.get("title", path.stem),
            "data_class": meta.get("data_class", "operational"),
            "text": raw.strip(),
        })
    return docs


# Near-duplicates a real knowledge base is full of. Deterministic, so every run
# indexes the same text. Gold codes from the small catalogue are excluded, so
# the right answer still lives in one document — but next to look-alikes.
_GOLD_CODES = {"КЦ-1180", "ПАР-500", "АМК-875", "ИНС-300", "ВИТ-Д3", "ГИГ-210", "ОМЗ-020"}
_FAMILIES = [
    ("АМК", "Амоксиклав", "Антибиотики"), ("АМО", "Амоксициллин", "Антибиотики"),
    ("АЗИ", "Азитромицин", "Антибиотики"), ("ЦФТ", "Цефтриаксон", "Антибиотики"),
    ("КЦ", "Кардиомагнил", "Сердечно-сосудистые"), ("АСК", "Аспирин Кардио", "Сердечно-сосудистые"),
    ("БИС", "Бисопролол", "Сердечно-сосудистые"), ("ЛОЗ", "Лозартан", "Сердечно-сосудистые"),
    ("ПАР", "Парацетамол", "Анальгетики"), ("ИБУ", "Ибупрофен", "Анальгетики"),
    ("НИМ", "Нимесулид", "Анальгетики"), ("КЕТ", "Кеторол", "Анальгетики"),
    ("ИНС", "Инсулин", "Инсулины"), ("МЕТ", "Метформин", "Эндокринология"),
    ("ОМЗ", "Омепразол", "Гастроэнтерология"), ("ПАН", "Пантопразол", "Гастроэнтерология"),
    ("ВИТ", "Витамин", "Витамины"), ("МАГ", "Магне B6", "Витамины"),
    ("ГИГ", "Средство гигиены", "Гигиена"), ("ЛОР", "Лоратадин", "Антигистаминные"),
]
_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
           "сентябрь", "октябрь", "ноябрь", "декабрь"]


def stress_docs() -> list[dict]:
    import random

    rnd = random.Random(7)
    docs: list[dict] = []
    rows = ["| Код | Наименование | Группа | Цена, сомони |", "| --- | --- | --- | --- |"]
    for prefix, name, group in _FAMILIES:
        for _ in range(20):
            code = f"{prefix}-{rnd.randint(100, 1999)}"
            if code in _GOLD_CODES:
                continue
            dose = rnd.choice([5, 10, 20, 40, 50, 75, 100, 125, 250, 400, 500, 625, 850, 875, 1000])
            pack = rnd.choice([10, 14, 20, 28, 30, 50, 60, 100])
            price = rnd.randint(800, 45000) / 100
            rows.append(f"| {code} | {name} {dose} мг №{pack} | {group} | {price:.2f} |".replace(".", ",", 1))
    docs.append({"key": "s_catalog", "title": "Прайс-лист центрального склада: полный перечень",
                 "data_class": "operational", "text": "# Прайс-лист центрального склада\n\n" + "\n".join(rows)})
    for i, month in enumerate(_MONTHS[:8]):
        markup = round(rnd.uniform(25.5, 29.5), 1)
        docs.append({
            "key": f"s_month_{i + 1:02d}", "data_class": "financial",
            "title": f"Управленческий отчёт за {month} 2026 года",
            "text": (f"# Управленческий отчёт за {month} 2026 года\n\n## Ключевые показатели\n\n"
                     f"Средняя торговая наценка по сети за {month} составила {markup:.1f} %. ".replace(".", ",", 1)
                     + f"Доля возвратов от выручки — {rnd.uniform(0.3, 0.9):.1f} %. ".replace(".", ",", 1)
                     + f"Средний чек изменился на {rnd.randint(-5, 9)} % к прошлому месяцу.\n\n"
                     "## Расходы\n\nАрендные платежи и логистика — в пределах бюджета."),
        })
    for n, (store, fridge) in enumerate([("№1 «Центральная»", "Liebherr FKUv 1610"),
                                         ("№2 «Сино»", "Pozis ХФ-400"),
                                         ("№3 «Исмоили»", "Pozis ХФ-250"),
                                         ("№4 «Сугд»", "Liebherr FKv 503"),
                                         ("№5 «Вахш»", "Бирюса 155"),
                                         ("№6 «Хатлон»", "Pozis ХФ-140")], 1):
        docs.append({
            "key": f"s_store_{n}", "data_class": "operational",
            "title": f"Паспорт аптеки {store}: оборудование и ответственные",
            "text": (f"# Паспорт аптеки {store}\n\n## Холодильное оборудование\n\n"
                     f"Фармацевтический холодильник {fridge}, инвентарный номер ХО-{100 + n}. "
                     f"Сервисная организация «ТехноХолод», телефон +992 37 240-{10 + n}-{20 + n}. "
                     "Плановое техническое обслуживание — раз в полгода.\n\n## Ответственные\n\n"
                     f"Ответственный за холодовую цепь — старший фармацевт смены. "
                     f"Ключи от материальной комнаты хранятся у заведующего."),
        })
    docs.append({
        "key": "s_payroll_2025", "data_class": "hr",
        "title": "Положение об оплате труда сотрудников аптек на 2025 год (утратило силу)",
        "text": ("# Положение об оплате труда на 2025 год\n\n## Должностные оклады\n\n"
                 "| Должность | Оклад в месяц |\n| --- | --- |\n| Заведующий аптекой | 6 200 сомони |\n"
                 "| Провизор | 4 700 сомони |\n| Фармацевт | 3 900 сомони |\n| Кассир-консультант | 3 000 сомони |\n\n"
                 "## Надбавки\n\nЗа работу в ночные смены начисляется доплата 15 % часовой ставки."),
    })
    docs.append({
        "key": "s_supplier_dorutrans", "data_class": "financial",
        "title": "Договор поставки с ООО «Дору-Транс» — краткое изложение",
        "text": ("# Договор поставки с ООО «Дору-Транс»\n\n## Условия оплаты\n\n"
                 "Отсрочка платежа составляет 30 календарных дней. При предоплате скидка 2 %. "
                 "Минимальная сумма поставки — 8 000 сомони. Договор действует до 30 июня 2026 года.\n\n"
                 "## Ответственность\n\nПеня за просрочку поставки — 0,2 % в день."),
    })
    return docs


class CachedEmbedder:
    """Wraps the real embedder; identical texts are embedded once, ever."""

    def __init__(self, inner, path: Path) -> None:
        self.inner = inner
        self.dim = inner.dim
        self.path = path
        self.cache: dict[str, list[float]] = {}
        if path.exists():
            self.cache = json.loads(path.read_text())
        self.tag = f"{type(inner).__name__}:{getattr(inner, 'model', '')}:{inner.dim}"

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.tag}\n{text}".encode()).hexdigest()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if self._key(t) not in self.cache]
        if missing:
            vecs = await self.inner.embed(missing)
            for t, v in zip(missing, vecs):
                self.cache[self._key(t)] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.cache))
        return [self.cache[self._key(t)] for t in texts]


# ----------------------------------------------------------------- grading

_SPACE_IN_NUMBER = re.compile(r"(?<=\d)[\s   ]+(?=\d)")
# English thousands separator: "94,582.90" / "1,216,404" (a comma followed by
# exactly three digits); a Russian decimal comma has one or two ("27,4").
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def norm(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = _SPACE_IN_NUMBER.sub("", text)
    text = _THOUSANDS_COMMA.sub("", text)
    return _DECIMAL_COMMA.sub(".", text)


def grade(q: dict, answer, title_to_key: dict[str, str]) -> dict:
    text = norm(answer.text)
    exp = q.get("expect", {})
    missing = [s for s in exp.get("all", []) if norm(s) not in text]
    any_ok = (not exp.get("any")) or any(norm(s) in text for s in exp["any"])
    leaked = [s for s in exp.get("none", []) if norm(s) in text]
    correct = not missing and any_ok and not leaked

    gold = set(q.get("gold") or [])
    shown = [title_to_key.get(r["title"], r["title"]) for r in answer.diagnostics.get("retrieved", [])]
    cited = [title_to_key.get(c.title, c.title) for c in answer.citations if c.document_id != "web"]
    out = {
        "correct": correct,
        "missing": missing,
        "any_ok": any_ok,
        "leaked": leaked,
        "shown_docs": shown,
        "cited_docs": cited,
        "retrieval_hit": (bool(gold & set(shown)) if gold else None),
        "citation_precision": (
            (sum(1 for d in cited if d in gold) / len(cited)) if gold and cited else None
        ),
        "cited_gold": (bool(gold & set(cited)) if gold else None),
        "noise_shown": sum(1 for d in shown if gold and d not in gold),
    }
    return out


# ------------------------------------------------------------------ runner

def principal(role: str) -> Principal:
    return Principal(TENANT, f"eval-{role}", (role,))


async def add_database(platform) -> None:
    """The testbench pharmacy DB as a free read-only query skill (finance+)."""
    from karag.connectors.registry import ConnectorSpec
    from karag.connectors.sql import SqlConnector
    from karag.integrations.dbsetup import make_query_skill, schema_summary

    if not DB_PATH.exists():
        print(f"! {DB_PATH} missing — run: python testbench/build.py (data questions will fail)")
        return
    conn = SqlConnector(sqlite_path=str(DB_PATH), timeout_s=10)
    schema = await conn.introspect(max_tables=20, sample_rows=1)
    spec = ConnectorSpec(
        id="conn_eval", tenant_id=TENANT, name="Аптеки", kind="sql_sqlite",
        config={"path": str(DB_PATH)},
        metadata={
            "description": "База данных сети аптек: аптеки, товары, продажи, остатки, сотрудники.",
            "schema_summary": schema_summary(schema),
            "data_class": DataClass.FINANCIAL.value,
            "free_query": True,
            **({"table_classes": {"employees": "hr"}} if os.environ.get("EVAL_TABLE_CLASSES") else {}),
        },
    )
    platform.registry.register(make_query_skill(spec, conn))


async def build(args) -> tuple:
    env = Settings.from_env()
    overrides = dict(
        store="memory", app_store="memory", chat_store="memory", usage_store="memory",
        web_search="none", web_fetch="0", engineer_enabled=False,
        fallback_generator=None,  # measure the model under test, not a fallback
        rate_limit_per_minute=0,  # the runner fires questions faster than people do
    )
    if args.model:
        overrides["anthropic_model"] = args.model
        overrides["generator"] = "openai" if args.model.startswith("gpt") else "anthropic"
        if args.model.startswith("gpt"):
            overrides["openai_model"] = args.model
    if args.effort:
        overrides["anthropic_effort"] = args.effort
    if args.retrieval:
        overrides["retrieval_mode"] = args.retrieval
    if args.contextual is not None:
        overrides["contextual_chunks"] = args.contextual == "1"
    if args.agentic is not None:
        overrides["agentic_search"] = args.agentic == "1"
    if args.relative_floor is not None:
        overrides["relative_floor"] = args.relative_floor
    if args.min_score is not None:
        overrides["min_score"] = args.min_score
    if args.top_k is not None:
        overrides["top_k"] = args.top_k
    settings = dataclasses.replace(env, **overrides)
    platform = build_platform(settings)
    platform.gateway.embedder = CachedEmbedder(
        platform.gateway.embedder, ROOT / ".cache" / "embeddings.json"
    )
    # the services captured the embedder at build time
    platform.ingestion._embedder = platform.gateway.embedder
    platform.retrieval._embedder = platform.gateway.embedder

    admin = Principal(TENANT, "eval-admin", ("admin",))
    docs = load_corpus() + (stress_docs() if args.stress else [])
    for d in docs:
        await platform.ingestion.ingest_document(
            admin, title=d["title"], text=d["text"], data_class=DataClass(d["data_class"]),
        )
    await add_database(platform)
    return settings, platform, docs


async def run_one(platform, q, sem, title_to_key, prices) -> dict:
    history = []
    for user, assistant in q.get("history", []):
        history.append(ChatMessage(role=MsgRole.USER, content=user))
        history.append(ChatMessage(role=MsgRole.ASSISTANT, content=assistant))
    async with sem:
        t0 = time.perf_counter()
        try:
            answer = await platform.orchestrator.ask(principal(q["role"]), q["question"], history=history)
            error = None
        except Exception as exc:  # noqa: BLE001
            return {"id": q["id"], "kind": q["kind"], "error": f"{type(exc).__name__}: {exc}",
                    "correct": False, "seconds": time.perf_counter() - t0}
        seconds = time.perf_counter() - t0
    usage = answer.diagnostics.get("usage", {})
    model = usage.get("served_by") or answer.diagnostics.get("model", "")
    cost = prices.cost(model, billable_input_tokens(usage, model), int(usage.get("output_tokens", 0)))
    g = grade(q, answer, title_to_key)
    return {
        "id": q["id"], "kind": q["kind"], "lang": q["lang"], "role": q["role"],
        "question": q["question"], "answer": answer.text, "error": error,
        "skills": answer.skills_used, "queries": answer.queries_shown,
        "seconds": round(seconds, 2), "usd": round(cost.total_usd, 5),
        "calls": usage.get("calls", 0), "model": model, **g,
    }


async def retrieval_only(platform, questions, title_to_key) -> list[dict]:
    rows = []
    for q in questions:
        if not q.get("gold"):
            continue
        history = [ChatMessage(role=MsgRole.USER, content=u) for u, _ in q.get("history", [])]
        chunks = await platform.orchestrator._retrieve(principal(q["role"]), q["question"], history)
        shown = [title_to_key.get(r.chunk.title, r.chunk.title) for r in chunks]
        gold = set(q["gold"])
        rows.append({
            "id": q["id"], "hit": bool(gold & set(shown)),
            "first_gold_rank": next((i + 1 for i, d in enumerate(shown) if d in gold), None),
            "shown": len(shown), "noise": sum(1 for d in shown if d not in gold),
        })
    return rows


def summarise(rows: list[dict]) -> dict:
    def rate(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(1 for x in xs if x) / len(xs), 3) if xs else None

    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
    secs = sorted(r["seconds"] for r in rows)
    precisions = [r["citation_precision"] for r in rows if r.get("citation_precision") is not None]
    noise = [r.get("noise_shown", 0) for r in rows if r["kind"] in ("fact", "mixed")]
    return {
        "questions": len(rows),
        "accuracy": rate([r["correct"] for r in rows]),
        "by_kind": {k: rate([r["correct"] for r in v]) for k, v in sorted(by_kind.items())},
        "errors": sum(1 for r in rows if r.get("error")),
        "retrieval_hit": rate([r.get("retrieval_hit") for r in rows]),
        "cited_gold": rate([r.get("cited_gold") for r in rows]),
        "citation_precision": round(statistics.mean(precisions), 3) if precisions else None,
        "avg_noise_docs_shown": round(statistics.mean(noise), 2) if noise else None,
        "usd_total": round(sum(r.get("usd", 0) for r in rows), 4),
        "usd_per_answer": round(statistics.mean([r.get("usd", 0) for r in rows]), 5) if rows else None,
        "seconds_median": round(statistics.median(secs), 1) if secs else None,
        "seconds_p90": round(secs[int(len(secs) * 0.9) - 1], 1) if secs else None,
        "model_calls_avg": round(statistics.mean([r.get("calls", 0) for r in rows]), 2) if rows else None,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--retrieval", choices=["dense", "hybrid"])
    ap.add_argument("--contextual", choices=["0", "1"])
    ap.add_argument("--agentic", choices=["0", "1"])
    ap.add_argument("--relative-floor", type=float, dest="relative_floor")
    ap.add_argument("--min-score", type=float, dest="min_score")
    ap.add_argument("--top-k", type=int, dest="top_k")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--stress", action="store_true",
                    help="add ~20 look-alike documents (old versions, near-duplicate codes, monthly reports)")
    args = ap.parse_args()

    questions = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    settings, platform, docs = await build(args)
    title_to_key = {d["title"]: d["key"] for d in docs}
    config = {
        "model": platform.gateway.generator.model, "effort": settings.anthropic_effort,
        "retrieval": settings.retrieval_mode, "contextual": settings.contextual_chunks,
        "agentic": settings.agentic_search, "relative_floor": settings.relative_floor,
        "min_score": settings.min_score, "top_k": settings.top_k,
        "embedder": platform.gateway.embedder.tag, "stress": args.stress,
    }
    print("config:", json.dumps(config, ensure_ascii=False))

    if args.retrieval_only:
        rows = await retrieval_only(platform, questions, title_to_key)
        hit = sum(r["hit"] for r in rows) / len(rows)
        mrr = statistics.mean(1 / r["first_gold_rank"] if r["first_gold_rank"] else 0 for r in rows)
        noise = statistics.mean(r["noise"] for r in rows)
        print(f"retrieval-only: hit={hit:.3f} mrr={mrr:.3f} noise_passages={noise:.2f} n={len(rows)}")
        for r in rows:
            if not r["hit"]:
                print("  miss:", r["id"])
        summary = {"hit": round(hit, 3), "mrr": round(mrr, 3), "noise": round(noise, 2)}
    else:
        sem = asyncio.Semaphore(args.concurrency)
        prices = PriceList.from_env()
        rows = await asyncio.gather(*(run_one(platform, q, sem, title_to_key, prices) for q in questions))
        summary = summarise(rows)
        for r in rows:
            if not r["correct"]:
                why = r.get("error") or (f"missing {r.get('missing')}" if r.get("missing") else "") \
                    or ("leaked " + str(r.get("leaked")) if r.get("leaked") else "") or "expected wording absent"
                print(f"  ✗ {r['id']:<24} {why} :: {(r.get('answer') or '')[:140]!r}")
        print(json.dumps(summary, ensure_ascii=False, indent=1))

    out = ROOT / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"config": config, "summary": summary, "rows": rows},
                              ensure_ascii=False, indent=1))
    print("saved", out.relative_to(REPO))


if __name__ == "__main__":
    asyncio.run(main())
