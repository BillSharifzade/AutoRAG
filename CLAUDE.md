# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

KARAG (Koinot Auto RAG) is a multi-tenant, RBAC-governed platform. Each company in a group gets its own AI over its own data: a **knowledge plane** (RAG over documents, with citations) and a **data plane** (verified, parameterized "skills"; the model never writes raw SQL against business data). The backend is Python in `karag/` and the console is Next.js in `web/`. Comments like `§5` or `§7` cite sections of `KARAG_Concept.html`, the original concept doc.

## Commands

Python ≥3.11. The core is stdlib-only, and providers and drivers are optional extras in `pyproject.toml` (`api`, `anthropic`, `ollama`, `pgvector`, `mysql`, `secrets`, `ingestion`, `fast`, `dev`). Scripts import `karag` from the repo root, so they need `PYTHONPATH=.`.

```bash
.venv/bin/python -m pytest -q                                  # full offline suite: no network, no keys
.venv/bin/python -m pytest tests/test_rbac.py -q               # one file
.venv/bin/python -m pytest tests/test_rbac.py::test_name -q    # one test (or -k <expr>)
.venv/bin/ruff check karag evals scripts --select F            # what CI lints (pyflakes rules)

# answer quality against the REAL model (costs cents; isolated in-memory platform)
PYTHONPATH=. .venv/bin/python evals/run_eval.py --stress --label mychange
PYTHONPATH=. .venv/bin/python evals/run_eval.py --stress --retrieval-only   # free, no model calls

# env-gated tests (they auto-skip otherwise)
KARAG_TEST_PG_DSN="host=127.0.0.1 port=5432 dbname=karag user=karag" .venv/bin/python -m pytest tests/integration/test_pgvector.py
KARAG_TEST_LIBREOFFICE=1 .venv/bin/python -m pytest tests/test_pptx.py

# run the real processes (load .env first)
set -a; source .env; set +a
PYTHONPATH=. .venv/bin/python scripts/serve.py            # API on :8000
PYTHONPATH=. .venv/bin/python scripts/run_scheduler.py    # alert rules + hourly API-source sync
PYTHONPATH=. .venv/bin/python scripts/run_telegram_bot.py # dev long-polling bot
PYTHONPATH=. .venv/bin/python scripts/demo.py             # offline end-to-end demo
PYTHONPATH=. .venv/bin/python scripts/smoke_claude.py     # live check of the production model path (needs a key)

# console (proxies /v1/* and /health to KARAG_API_URL, default http://127.0.0.1:8000)
cd web && npm run dev      # or: npm run build && npm run start
cd web && npm run lint

docker compose up --build  # api :8000 + web :3000 + scheduler; state in ./data
./testbench/up.sh          # demo API + Postgres + MySQL fixtures for the Data page (see testbench/README.md)
```

Start the API with `scripts/serve.py`, not `uvicorn karag.api.app:app`. `serve.py` chains env tokens with database accounts (`ChainResolver`). The module-level `app` in `karag/api/app.py` only knows the `KARAG_TOKENS` map. Tokens use the format `token:tenant:user:role1|role2`, and the dev tokens are `tkn_ceo`, `tkn_admin`, `tkn_emp`, `tkn_eng` and `tkn_ops`.

## Architecture

### Security invariants (the point of the project)
- **RBAC is enforced at retrieval time, never by filtering the answer.** `karag/rbac.py` holds an explicit, default-deny role → `DataClass` matrix. The resolved classes, plus the tenant, are applied *inside* `VectorStore.search`, before scoring. That signature is the security contract, so any new store must keep the filter inside the query. Unclassified content fails closed to the most restrictive class.
- **Numbers come only from skills.** RAG retrieves text and cites it. It never computes figures.
- **Non-disclosure:** `SkillRegistry.visible_for(principal)` decides which tools the model is even offered. An unauthorized caller gets `SkillNotFound`, not `AccessDenied`. Tests assert this, and it is the stronger property. The HTTP authoring endpoints do return 403 with a reason, because trusted staff use them.
- Every operation runs under a `Principal` (tenant, user, roles). Agentic admin skills (`skills/admin_skills.py`) call the same services as the REST API under the caller's own principal, so RBAC is enforced in one place.

### Composition
- `karag/config.py` `Settings.from_env()` reads `KARAG_*` env vars. `karag/factory.py` `build_platform()` is the only place that knows concrete providers. It returns a `Platform` dataclass holding every service. Provider modules are imported lazily inside the `build_*` functions so optional deps stay optional.
- Every persistent store has a `memory` and a `sqlite` implementation, chosen by `app_store` / `chat_store` / `usage_store` / `store` (vectors: `memory | sqlite | pgvector`). Tests use the memory stores and the `fake` generator/embedder.
- `llm/base.py` defines the `Generator` / `Embedder` protocols behind a `Gateway`. Embeddings are a separate provider because Claude has no embeddings endpoint. `llm/fallback.py` chains generators (`KARAG_FALLBACK_GENERATOR=a,b`), and usage is billed to whichever model actually served (`served_by`). A provider that fails mid-stream makes the chain emit `STREAM_RESET`, which reaches the console as a `reset` SSE event.
- Admin skills are registered *after* `Platform(...)` is built, because they need the assembled platform. The registry is shared by reference, so the orchestrator still sees them. `orchestrator.guard` (`budget.UsageGuard`: per-user rate limit + per-tenant monthly budget) is attached the same way, after the directory exists, and checked before any model call.
- Model choice was measured with `evals/` (results in `evals/README.md`): Sonnet 5.5 at medium effort answers, Opus 5.5 runs engineer turns, Haiku 5.5 reads scanned PDFs (`llm/ocr.py`). Re-run the eval before changing the model, the prompts or retrieval.

### Claude request rules (`llm/anthropic_adapter.py`)
Current models keep **preserved thinking**. Inside one turn's tool loop the assistant's original content blocks, thinking included, are replayed verbatim (`ChatMessage.provider_blocks`). The `system` prompt and the `tools` list must stay byte-identical for the whole turn. That is why the final "answer now" call keeps the tools and sends `tool_choice: "none"`, never `tools=None`: changing the tools invalidates every thinking block and the prompt cache. Requests also send `block_binding: drop_block` (a mistake degrades instead of failing with a 400), server-side refusal `fallbacks: "default"`, an explicit `output_config.effort`, eager tool-input streaming (the executor validates inputs), and the `anthropic-workspace-id` header when `KARAG_ANTHROPIC_WORKSPACE_ID` is set. Do not add `temperature`, `budget_tokens`, forced `tool_choice` (`any`/`tool`) or assistant prefill: current models reject all four with a 400.

### Skills
`SkillRegistry` is keyed by `(tenant_id, name)`. Skills come from several sources, all wired in `factory.py`:
- **Code:** `skills/samples.py`. These are demo-only and enabled with `KARAG_DEMO_SKILLS=1`.
- **Stored definitions:** `skills/definitions.py` + `skills/catalog.py` + `connectors/registry.py`. These are authored through the API/console, validated at write time (read-only SQL, closed param schema, declared params actually bound) and materialised into the registry at boot. Boot failures go to `platform.skill_load_errors` and are shown on `/health`.
- **Guided integrations:** `integrations/` (`api/integrations.py` mounts their routes). They add `fetch_<name>` skills for API sources and `query_<name>` skills for connected databases. DB credentials are sealed with `KARAG_SECRET_KEY`. Outbound fetches go through the SSRF guard in `web/guard.py`, and `KARAG_WEB_ALLOW_PRIVATE_HOSTS` is the explicit per-host exception. A query skill's audience is the connection's `data_class`. `metadata.table_classes` / `hidden_tables` can only narrow it per table: `dbsetup.check_query` refuses a statement naming a blocked table, plus SQL-from-a-string functions (`query_to_xml`, `dblink`…). Large or narrowed schemas are not inlined in the tool description; the model calls the skill without `sql` to get a per-caller filtered schema.
- **Built-ins:** file authoring (`skills/authoring.py` → `office/`, stdlib OOXML; artifact bytes never enter model context), self-knowledge (`selfknowledge/`, read-only window onto this repo), web search/fetch (`web/`), engineer (`engineer/`), admin.

### Orchestrator (`karag/orchestrator.py`)
This is a bounded agentic loop:
1. Retrieve RBAC-filtered chunks. Greetings retrieve nothing, short follow-ups are searched with the previous question, each document gets at most `max_per_document` chunks, and a relevance gate keeps passages whose `dense_score` is ≥ `relative_floor` × the best one's (strong keyword hits always pass).
2. Offer the visible skills as tools, plus the orchestrator-native `search_documents` tool. That tool runs the same RBAC-filtered retrieval, continues the `[n]` numbering, and is exempt from assistant allow-lists, because documents belong to every assistant.
3. Execute tool calls under the principal, with a timeout.

The answer's `citations` are only the markers its text actually cites (`cited_markers`). `diagnostics["retrieved"]` lists everything the model was shown, which the evaluation uses.

Retrieval (`knowledge/retrieve.py`) is hybrid by default. A vector search and `VectorStore.keyword_search` run side by side and are fused with RRF. Keyword search goes through `knowledge/lexical.py` (Snowball Russian, light Tajik/English stemming, codes like `амк-875` kept whole), and the same `terms()` is used at index and query time. SQLite uses FTS5 and Postgres its full-text index; both backfill themselves on start-up. Ingestion chunks by Markdown section (`chunking.chunk_document`), stores the heading on the `Chunk`, and embeds `embedding_text(title, heading, text)`.

Any exception a skill raises becomes a tool error the model reads, never a failed turn. Retrieved text is fenced as untrusted data, and `request_context.mark_untrusted_content` records that it happened. Streaming goes through an `EventCallback` (`status → tool → delta → done`), served as SSE at `POST /v1/chats/{id}/stream`. When the caller holds `karag_engineer`, the whole turn runs on the engineer model (`build_engineer_generator`).

### HTTP layer (`karag/api/`)
`app.py` `create_app(platform, resolver)` is an app factory, tested with `TestClient`. It holds the exception handlers and `principal_from`, then calls `mount(app, ctx)` on each module in `api/routes/` (platform, skills, admin, documents, chat, webhooks) with an `ApiContext`. Request models and shared helpers live in `api/common.py`. Domain errors map to HTTP status once, in exception handlers (`AccessDenied`→403, `ValidationError`→400, `NotFoundError`→404, `RateLimited`/`BudgetExceeded`→429, `GenerationError`→502). The `principal_from` dependency **must stay `async`**. It sets a `ContextVar` (IP, user agent, roles) that the audit log reads deep in the stack, and a sync dependency runs in a worker thread with a copied context, which silently empties every audit record.

### Guarded self-modification (`karag/engineer/`)
`guard.py` holds the whole policy: `PROTECTED_PATHS` / `PROTECTED_PREFIXES` (rbac, tenants, auth, the vector-store contract, the SQL guard, and `karag/engineer/` itself), plus a refusal on any turn that carried untrusted content. `GitWorkspace` operates on the **real repo** at `KARAG_REPO_ROOT`. It creates a branch, commits, runs pytest, diffs, and always restores the original branch. It refuses to run on a dirty tree.

### Web console (`web/`)
- **Next.js 16 has breaking changes versus training data** (for example, middleware is now "proxy"). Read `web/node_modules/next/dist/docs/` before writing Next code (see `web/AGENTS.md`).
- `next.config.ts` rewrites `/v1/*` and `/health` to `KARAG_API_URL`, so there is no CORS. The rewrite is resolved at **build** time, which is why Docker passes it as a build arg.
- `src/lib/api.ts` is the typed client and `src/lib/auth.tsx` is the token/theme context (token in `localStorage['karag_token']`).
- Interface text is Russian first with English as a switch. Dictionaries live per page in `src/i18n/*.ts`, and you read them with `useT()`. `src/lib/words.ts` translates platform terms (data classes, roles, audit actions) into plain business language. Add wording there instead of inlining it, because the users are pharmacists and finance staff, not engineers. Answer language is separate: it always follows the question.
- Shared page furniture lives in `components/pro.tsx`. The sign-in screen (`ConnectGate` in `components/shell.tsx`) and the Usage page are the frozen design reference. `components/ui.tsx` is shared with them, so extend it instead of changing existing variants.

## Gotchas
- The system prompt includes the platform handbook (`selfknowledge/handbook.py`). Broad substring asserts on prompt text (for example `"Russian" not in system`) break whenever prompt content grows, so assert on the specific directive instead.
- In Next dev, use `http://localhost:3000`, not `127.0.0.1`. Next 16 blocks cross-origin `/_next/*` from `127.0.0.1`, and the page then renders as an empty body with no error.
- A docker-compose instance with real data may already hold :3000/:8000. Check `docker ps` before starting dev servers, or a failed bind sends your test traffic to the real instance. Use other ports (`npm run dev -- -p 3100` with `KARAG_API_URL` set).
- The SQLite vector store caches each tenant's vectors in memory and invalidates the cache through `PRAGMA data_version`, so writes from the scheduler process are seen. Keep any new write path either through the store or committed on its own connection.
- The eval runner's numbers are only comparable at the same settings: use `--stress`, and re-score old results if you change the grader (`norm()` in `evals/run_eval.py`).
- `.gitignore` anchors `/data/` on purpose. An unanchored `data/` once hid `web/src/app/data/` and `web/src/components/data/` from git.
- Local (non-docker) runs write SQLite files (`karag_app.db`, `karag_chats.db`, …) to the repo root via `.env` paths. Docker uses `./data`.
