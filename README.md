# KARAG — Koinot Auto RAG

A multi-tenant, RBAC-governed platform that gives every company in a group its
own AI over its own data: **knowledge** (RAG over documents, with citations) and
**data** (verified, parameterized "skills" — never raw SQL to the model).

Built provider-agnostic: the same code runs on a **deterministic offline fake**
(tests), a **free local Ollama** model, or **Claude Opus 4.8** in production —
selected by configuration, no application changes.

## Why this shape

* **Two planes, kept separate.** RAG retrieves *text* and cites it; it never
  computes numbers. Numbers come only from a human-written, verified skill. This
  is the concept doc's central rule, enforced in code.
* **Security at retrieval time, not in the prompt.** A principal's clearance is
  resolved to a set of data classes and applied *inside* the vector store's
  query, before scoring — forbidden content never enters the model's context.
  Tenant isolation works the same way. (You cannot "tell the model not to say
  it" once it has seen it — so it never sees it.)
* **Swappable providers.** Generation and embeddings sit behind `Generator` /
  `Embedder` protocols (Claude has no embeddings endpoint, so they're separate).
  The composition root is `karag/factory.py`.

## Layout

```
karag/
  domain.py         core types (Principal, Document, Chunk, DataClass, Answer)
  rbac.py           explicit, default-deny role -> data-class matrix
  tenants.py        tenants + accounts, hashed tokens, onboarding service
  llm/              base protocols + fake / ollama / anthropic / openai adapters
  vectorstore/      base + in-memory (tests) + sqlite + pgvector (prod)
  knowledge/        chunking, ingest, RBAC-filtered retrieve, RAG w/ citations,
                    classify.py (advisory data-class suggestion)
  connectors/       read-only SQL + REST, plus the stored connector registry
  skills/           verified data-plane tools: base, registry, executor, samples,
                    definitions.py + catalog.py (skills stored as data, not code)
  orchestrator.py   agentic loop unifying both planes under one principal
  scheduler.py      stored alert rules + the loop that evaluates them
  pricing.py        per-model token pricing for the cost dashboard
  api/              FastAPI app + pluggable auth (optional)
  config.py         env-driven settings   factory.py  composition root
sql/schema.sql      pgvector DDL          scripts/demo.py  end-to-end demo
web/                Next.js console: chat, assistants, documents, skills, admin,
                    audit, usage
tests/              285 tests: RBAC, isolation, retrieval, RAG, skills, catalog,
                    tenants, scheduler, language, orchestrator
```

## Run

The whole platform — API, console and alert scheduler — in one command:

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY and KARAG_TOKENS
docker compose up --build
```

| | |
|---|---|
| Console | <http://localhost:3000> — sign in with a token from `KARAG_TOKENS` |
| API | <http://localhost:8000> — `/health`, `/v1/*`, legacy console at `/ui` |

State is SQLite under `./data`, bind-mounted into the containers, so it survives
`docker compose down`. Point `KARAG_STORE` at pgvector for a real deployment.
The Telegram bot is opt-in — it needs `KARAG_TELEGRAM_BOT_TOKEN`:

```bash
docker compose --profile telegram up
```

### Without Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip pytest pytest-asyncio

# 1) Offline test suite (no network, no keys) — the security invariants
.venv/bin/python -m pytest -q

# 2) End-to-end demo (offline fake gateway)
PYTHONPATH=. .venv/bin/python scripts/demo.py
```

### Free real model (Ollama)

```bash
ollama pull llama3.1 && ollama pull nomic-embed-text
.venv/bin/pip install httpx
export KARAG_GENERATOR=ollama KARAG_EMBEDDER=ollama KARAG_EMBED_DIM=768
PYTHONPATH=. .venv/bin/python scripts/demo.py
```

### Production (Claude Opus 4.8 + pgvector)

```bash
.venv/bin/pip install anthropic 'psycopg[binary]' fastapi uvicorn pydantic httpx
psql "$KARAG_PG_DSN" -f sql/schema.sql        # adjust vector(dim) to your embedder
export KARAG_GENERATOR=anthropic KARAG_ANTHROPIC_MODEL=claude-opus-4-8
export ANTHROPIC_API_KEY=sk-ant-...
export KARAG_EMBEDDER=ollama KARAG_STORE=pgvector KARAG_PG_DSN=postgresql://...
export KARAG_TOKENS="tkn_ceo:koinoti:ceo1:ceo,tkn_fin:koinoti:fin1:finance"
export KARAG_APP_STORE=sqlite KARAG_APP_DB=./karag_app.db   # tenants, skills, audit
PYTHONPATH=. .venv/bin/uvicorn karag.api.app:app
```

### The three processes

```bash
set -a; source .env; set +a

# API  (every /v1/* endpoint; the console is the Next.js app in web/)
PYTHONPATH=. .venv/bin/python scripts/serve.py

# Proactive alerts — evaluates stored rules on their own cadence
PYTHONPATH=. .venv/bin/python scripts/run_scheduler.py

# Telegram bot (development long-polling; production uses the webhook)
PYTHONPATH=. .venv/bin/python scripts/run_telegram_bot.py
```

The Next.js console is separate: `cd web && npm run build && npm run start`
(it proxies `/v1/*` and `/health` to the API on :8000).

See `.env.example` for all settings.

## Data classes & roles

Classes: `public · operational · hr · financial · regulated` (unclassified →
most restrictive, fail-closed). The role → class grants live, auditable, in
`karag/rbac.py`. `ceo` sees all classes **within its own tenant only** — never
another tenant's data.

## Extending

* **New skill (no code):** register a read-only data connection, then author the
  skill through `/skills` in the console (or `POST /v1/connectors` +
  `POST /v1/skills/definitions`). The definition is stored, validated at write
  time (read-only SQL, closed parameter schema, declared params actually bound),
  materialised into the live registry immediately, and reloaded on restart.
  `POST /v1/skills/definitions/{id}/test` runs it and shows the executed query —
  that is the §5 "build and test once" loop.
* **New skill (in code):** construct a `Skill` (name, JSON schema, handler,
  `required_data_class`, `required_roles`, `tenant_id`) and
  `registry.register(...)`. See `karag/skills/samples.py`.
* **New provider:** implement `Generator` or `Embedder` and wire it in
  `factory.py`. Everything above is unchanged.
* **New store:** implement the `VectorStore` protocol (the `search` signature is
  the security contract — keep the tenant + class filter inside it).

## Implemented

* **Two planes** — knowledge (RAG + citations) and data (verified skills).
* **Robust turns** — a skill that raises anything (a renamed table, an API
  that is down) becomes a tool error the model reads and routes around, never
  a failed request; skills run under a timeout (`KARAG_SKILL_TIMEOUT`). Every
  model call of a tool-calling turn is metered, cached prompt tokens are billed
  at their real weights, and the system prompt + tool list carry prompt-cache
  breakpoints (≈5k tokens cached per request on Claude).
* **Retrieval hygiene** — greetings retrieve nothing; a short follow-up is
  searched together with the question it follows; at most
  `KARAG_MAX_PER_DOCUMENT` chunks per document; an optional score floor
  (`KARAG_MIN_SCORE`); sources are fenced and labelled as untrusted data.
  Re-adding a document under an existing title *replaces* the old copy
  (`scripts/dedupe_documents.py` cleans up databases filled before this).
* **Retrieval-time RBAC + tenant isolation** — enforced inside the store.
* **Real data connectors** — read-only SQL (`SqlConnector`, SQLite + Postgres,
  with statement guards/row limits/timeouts) and REST; `make_sql_skill` turns a
  parameterized query into a verified, tenant-scoped skill.
* **Document ingestion** — `ingest_file` extracts text from `.docx/.xlsx/.pptx/
  .csv/.txt/.md` (stdlib) and `.pdf` (via `pypdf`) into the knowledge plane.
* **Office generation (Phase 1.5)** — valid `.xlsx/.docx/.pptx/.csv` via stdlib
  OOXML, verified to open in LibreOffice; returned as `Artifact`s (bytes never
  enter the model's context).
* **Guided integrations (Data page)** — a non-engineer connects an **API**
  by pasting its address: the endpoint is fetched (through the SSRF guard),
  profiled, and the model explains what the data is and what each field means;
  the person corrects it, then saves it as a live `fetch_<name>` skill, as a
  knowledge document refreshed on a cadence (hourly by default; unchanged
  bytes are never rewritten — the scheduler process runs the sync), or both.
  A **database** is connected from login details (PostgreSQL, MySQL) or an
  uploaded file (`.sqlite` / `.db`, or a `mysqldump` / `pg_dump` `.sql`
  imported best-effort into SQLite with a report): the schema is read and
  described by the model, written into knowledge, and — switchable per
  connection — the assistant may write its own read-only SELECT through a
  `query_<name>` skill (read-only transaction, row limit, timeout, every query
  audited and shown with the answer). Credentials are sealed at rest with
  `KARAG_SECRET_KEY` and never served back.
* **Runtime skill registry** — skills live as *data*, not code: register a
  read-only connection, author a parameterised SQL/REST skill through the API or
  the `/skills` console page, test it (the executed query and rows come back),
  and it becomes a live tool immediately and after every restart. Validation at
  write time rejects write statements, stacked statements, open parameter
  schemas and undeclared bindings. An author may only expose a data class they
  are themselves cleared to read. Shared definitions form the §15 skill library:
  another company copies the *query*, bound to its own connection.
* **Application database** — tenants, accounts, connectors, skill definitions,
  assistants, alert rules and the audit trail persist (`KARAG_APP_STORE=sqlite`).
  Account tokens are stored hashed and compared in constant time; suspending a
  tenant or account locks it out on the next request.
* **Audit trail** — every ingest / retrieval / skill-exec / ask / authoring
  action logged with allow/deny, IP, user-agent and roles
  (`InMemoryAuditLog`, `SqliteAuditLog`, `JsonlAuditLog`).
* **Usage metering & cost** — per-tenant/user token + request accounting, split
  by the model that actually served each request (a fallback is billed to the
  fallback), priced at read time from a configurable rate table (`KARAG_PRICING`).
  An unpriced model is reported as such rather than guessed.
* **Multilingual (RU / TJ / EN)** — the answer always follows the language of
  the question, whatever language the documents are in. The console's own
  interface is Russian by default with English one click away.
* **Platform self-knowledge** — the assistant carries a handbook of what KARAG
  is plus a capability guide for the asking user's roles, and can read its own
  source (`search_codebase`, `read_source_file`) to answer implementation
  questions from the current code, citing `path:line`. Secrets, databases and
  `.git` are unreadable. New users get a one-time "show me around" tip that
  generates a tour for their actual role.
* **Operational skills** — the assistant can *act*: create accounts in bulk,
  set roles, suspend an account, report usage and cost, list the tenant's
  skills/documents/assistants/alerts. Every one runs under the caller's own
  Principal, so an admin's request succeeds and an employee's identical request
  is refused by the same code that guards the REST API. Batches are capped at
  100, destructive actions need an explicit confirm, and `platform_admin` /
  `karag_engineer` can never be granted this way.
* **Guarded self-modification** — a `karag_engineer` can ask for a source
  change. It is written on a fresh git branch by Opus 4.8, the full suite runs
  against it, and the diff waits on the Engineering page for a human to apply
  or discard; the running tree is never touched. Four independent gates:
  the platform-level role (grantable only by a platform operator), a
  deny-list no role can override (the RBAC matrix, the tenant directory, the
  auth layer, the guard itself), a refusal on any turn carrying untrusted
  content (prompt-injection barrier), and the human apply step.
* **Document catalogue** — list and delete what has been ingested, filtered by
  the same clearance as retrieval (a title you may not read is not shown), plus
  an **advisory** data-class suggestion at upload (§7: suggestion only — it is
  never auto-applied; unclassified still fails closed to the most restrictive).
* **Auth** — pluggable resolver: demo tokens *or* real **JWT (HS256, stdlib)**;
  SSO issues signed JWTs KARAG verifies.
* **No-code assistants** — create/edit a tenant-scoped assistant (name +
  instruction + skill allow-list: `null` = everything the person may use, `[]`
  = documents only, a list = exactly those) and ask through it; it can only
  *narrow* the caller's access. Everyone in the company may use an assistant;
  only its creator or an administrator may change or delete it. A chat whose
  assistant was deleted keeps working and says so (`assistant_missing`).
* **Office generation (Phase 1.5)** — `.pptx` decks use a branded layout
  (title-bar, accent rule, bulleted body, footer + page numbers) with a distinct
  cover slide; all formats verified to open headless in LibreOffice.
* **Inbound messenger bots** — Telegram + WhatsApp Cloud API webhooks
  (`/v1/webhooks/*`). A registered sender DMs the bot and gets the same
  RBAC-governed answer as the console; unknown senders are answered with a
  refusal and never processed (fail-closed). Outbound alert notifiers for both
  platforms also ship (`TelegramNotifier`, `WhatsAppNotifier`).
* **HTTP API** — FastAPI app (auth, ingest, file upload, ask, assistants CRUD,
  audit, usage, messenger webhooks), tested with `TestClient`; embeddable
  `deploy/widget.html`.
* **Web app (`web/`)** — Next.js 16 + TypeScript + Tailwind v4 frontend: chat
  with full provenance (plane badge, citations, executed queries, artifact
  downloads), assistant builder with live preview, drag-drop document ingestion
  with the classification suggestion and a delete-able knowledge catalogue, the
  **skill authoring** page (connections · editor · test run · library import),
  the **admin** page (tenant onboarding, account tokens, alert rules), audit
  table, usage + cost dashboard, and a Russian/English interface switch.
  Answers stream in as they are written (`POST /v1/chats/{id}/stream`, SSE:
  status → tool → delta → done) and stopping a reply cancels it on the server.
  Role-gated navigation; light/dark theme; proxies `/v1/*` to FastAPI
  (`npm run dev` in `web/`, backend on :8000 via `scripts/serve.py`).
* **Proactive alerts** — stored rules run a verified skill on their own cadence
  and notify (console / webhook / Telegram / WhatsApp) when the condition fires.
  `scripts/run_scheduler.py` is the long-lived process; `POST /v1/alerts/{id}/run`
  fires one on demand. Conditions are declared (`rows_returned`,
  `field_compare`, `always`), never evaluated code, and a rule can never be given
  roles its creator does not hold — so scheduling an alert is not a way to read a
  class you are not cleared for. Failing rules back off exponentially.
* **Generators** — `fake` (offline), `ollama` (free), `anthropic` (Claude Opus
  4.8, production target), `openai` (GPT; default `gpt-5.5`, keeps reasoning while
  tool-calling — live-verified end to end).
* **Embedders** — `fake`, `ollama` (free), `openai`, `voyage` (multilingual).
* **Stores** — `memory`, `sqlite` (persistent, stdlib), `pgvector` (validated
  against real Postgres 18 + pgvector 0.8.5).
* **Ops** — `Dockerfile` + `docker-compose.yml` (API + pgvector + Ollama).

## Testing

```bash
.venv/bin/python -m pytest -q          # 457 offline tests (5 env-gated skips)
```

The pgvector store has a real integration test, run it against a live database:

```bash
export KARAG_TEST_PG_DSN="host=127.0.0.1 port=5432 dbname=karag user=karag"
.venv/bin/python -m pytest tests/integration/test_pgvector.py
```

Validate the production model path end-to-end (needs an API key):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
PYTHONPATH=. .venv/bin/python scripts/smoke_claude.py
```

## Status / known gaps

Honest about what the concept doc asks for and this repo does *not* yet do:

* **No GigaChat adapter.** §9 offers GigaChat as the sensitive contour;
  production currently runs Claude with an OpenAI fallback. Deliberately out of
  scope for now — the adapter slots into `factory.py` like any other provider.
* **Phase 1 sends data to an external API.** §9 states this plainly and so do
  we: without a local GPU (Phase 2) every answer's context leaves the
  perimeter. Only the Ollama path is fully local today.
* **The app database is SQLite, not PostgreSQL.** §12 names Postgres; the
  stores are written against a narrow protocol and each has a SQLite
  implementation. Postgres-backed versions are a per-store port, not a redesign.
  The knowledge plane already runs on pgvector.
* **No SSO/OIDC.** Auth is bearer tokens (hashed, rotatable, per account) plus
  HS256 JWT verification, behind a `PrincipalResolver` protocol — an OIDC
  resolver is the natural next adapter.
* **Cost is a rate table, not an invoice.** Metering and per-model pricing exist;
  §17's subscription/onboarding billing does not.
* `.pptx` uses a branded multi-shape layout and opens in LibreOffice/Impress
  (headless render is CI-testable via `KARAG_TEST_LIBREOFFICE=1`); spot-check in
  PowerPoint for a design-critical deck.
* **Messenger bots** ship for Telegram + WhatsApp (inbound webhooks + outbound
  notifiers). Register senders via `KARAG_MESSENGER_SENDERS`; point
  Telegram/WhatsApp at `/v1/webhooks/*`. `scripts/run_telegram_bot.py` long-polls
  for development; a hosted always-on process is not included — webhooks assume
  a public HTTPS endpoint.
* **Auto-classification is keyword-based** and deliberately advisory. It is not
  a model call: sending a document of unknown sensitivity to an external API to
  ask how sensitive it is would be backwards.
* Real-Claude behaviour should be validated with `scripts/smoke_claude.py` before
  production (needs a key) — the free-model path is proven via `scripts/smoke_ollama.py`.
