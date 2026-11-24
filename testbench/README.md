# Testbench — a fake customer to point the platform at

Everything the **Data** page and the **Skills** page can consume, in one
command: a read-only demo API, a Postgres, a MySQL, a SQLite file and two real
SQL dumps — all holding the same pharmacy chain, so an answer from the API and
an answer from the database can be compared.

```bash
docker compose up -d      # the platform itself, if it is not running
./testbench/up.sh         # the testbench (≈1 min the first time: image pulls)
./testbench/down.sh       # remove it again
```

`up.sh` regenerates the data first (`build.py`), so every run seeds identical
rows and the numbers below stay true.

## What comes up

| | Reachable from the platform | Reachable from this machine |
| --- | --- | --- |
| Demo API | `http://karag-test-api:8100` | `http://localhost:8100` |
| Postgres 16 | `karag-test-pg:5432` | `localhost:55432` |
| MySQL 8.0 | `karag-test-mysql:3306` | `127.0.0.1:53306` |

Database `apteka`, login **`karag_reader` / `readonly`** — a user with `SELECT`
and nothing else, which is what the wizard should be given.

> The demo API lives on a private network, and KARAG refuses private addresses
> by design. `.env` therefore names it — `KARAG_WEB_ALLOW_PRIVATE_HOSTS=karag-test-api`
> — and *only* it: `http://karag-test-pg:5432/` or the cloud metadata address
> are still refused. Removing that line makes the API wizard unusable here; it
> does not affect the databases.

## Signing in

`http://localhost:3000`, with a token from `KARAG_TOKENS`:

| Token | Role | Can reach the Data page? |
| --- | --- | --- |
| `tkn_ceo` | ceo | yes |
| `tkn_admin` | admin | yes |
| `tkn_emp` | employee | no — 403, use it to check what a normal user sees |
| `tkn_eng` | engineer | no |
| `tkn_ops` | ops | no |

## 1 · Data → an API source

Paste any of these into the API wizard. They differ on purpose: the profiler
has to find the records in each shape.

| URL | What it exercises |
| --- | --- |
| `http://karag-test-api:8100/v1/products` | a bare JSON array, 40 records |
| `http://karag-test-api:8100/v1/sales/daily?limit=200` | records buried in an envelope (`data.items`) |
| `http://karag-test-api:8100/v1/stores.csv` | CSV instead of JSON |
| `http://karag-test-api:8100/v1/rate` | a single object — no record list at all |
| `http://karag-test-api:8100/v1/inventory?low=1` | query parameters; only items below the reorder point |
| `http://karag-test-api:8100/v1/broken` | a 500 — the source should fail loudly (502) |
| `http://karag-test-api:8100/v1/slow` | answers after 3 s |
| `http://karag-test-pg:5432/` | must be **refused**: not a cleared host |

Worth trying while you are there: leave a comment like *«это остатки на складе,
shortage = нужно дозаказать»* and re-run the description — the summary should
change. Save one source with **"fetch live"** (creates a `fetch_…` skill) and
one with **"keep a copy"** (creates a document and re-syncs on the interval;
`ka_rag-scheduler-1` runs the loop, and 300 s is the floor).

## 2 · Data → a database

**Login form** — Postgres: host `karag-test-pg`, port `5432`, database `apteka`,
user `karag_reader`, password `readonly`. MySQL: host `karag-test-mysql`, port
`3306`, same database and login. Both should read 5 tables and come back with a
Russian description of the schema.

**File drop** — `testbench/build/apteka.db` (SQLite, 748 KB).

**Dump import** — `testbench/build/apteka_pg_dump.sql` (real `pg_dump`) and
`apteka_mysql_dump.sql` (real `mysqldump`). The import is best-effort into
SQLite; both of these land clean — **14 563 rows, 0 failures**, five tables —
so anything less is a regression worth reporting.

Then flip the two switches per connection: **free query** (the model may write
its own read-only `SELECT`) and **knowledge** (the schema description becomes a
document). Set the audience to *«Руководство»* on the connection that exposes
`employees.monthly_salary`.

## 3 · Documents

Upload `testbench/build/schema_notes.md` — a short data guide with the 2026
plan (1 900 000 сомони, ≤35% рецептурных). It gives chat something to cite and
something to compare the live numbers against.

## 4 · Skills

On the Skills page, add a lookup over a saved connection. Two that work as-is:

```sql
SELECT s.name AS store, ROUND(SUM(x.amount), 2) AS revenue
FROM sales x JOIN stores s ON s.id = x.store_id
WHERE x.sold_on BETWEEN :from AND :to
GROUP BY s.name
ORDER BY revenue DESC
```

```sql
SELECT p.name AS product, SUM(x.quantity) AS units
FROM sales x JOIN products p ON p.id = x.product_id
WHERE p.category = :category
GROUP BY p.name
ORDER BY units DESC
LIMIT 10
```

Refusals to confirm: `DELETE FROM sales WHERE id = 1` must be rejected as a
write, and a lookup whose name collides with an existing tool must be rejected
too.

## 5 · Chat — and the answers to check it against

Ground truth for the whole seeded period (**2025-01-01 … 2026-08-31**):

| Question | Answer |
| --- | --- |
| Выручка сети за период | **1 216 404,90** сомони |
| Выручка за август 2026 | **65 377,10** |
| Лучшая аптека | **Аптека №1 «Центральная»** — 313 594 |
| Следующие две | «Сино» 251 270, «Исмоили» 215 094 |
| Категория с наибольшей выручкой | **Гигиена** — 467 566 |
| Товар-лидер по штукам | **Железо + фолиевая кислота** — 872 |
| Позиций ниже порога дозаказа | **39** |
| Доля рецептурных в выручке | **18,3 %** (план — не выше 35 %) |
| Месячный фонд оплаты труда | **139 950** сомони |

Plan-vs-fact is the interesting one: ask *«выполняем ли мы план по выручке на
2026 год?»* — the plan is in the uploaded document, the fact is in the database,
and a good answer uses both and says the period is incomplete.

RBAC to confirm with `tkn_emp`: no Data page, no `query_…` skill offered, and a
question about salaries answered with a refusal rather than a number.

## Files

`testbench/build/` (git-ignored, rebuild with `python testbench/build.py`):

| File | Use |
| --- | --- |
| `apteka.db` | SQLite upload |
| `apteka_pg_dump.sql`, `apteka_mysql_dump.sql` | dump import |
| `apteka_pg.sql`, `apteka_mysql.sql` | seed files used by `up.sh` |
| `pg_reader.sql`, `mysql_reader.sql` | the read-only logins |
| `schema_notes.md` | document to upload |

The dataset lives in `dataset.py` (fixed seed — edit it and re-run `up.sh` if
you want different numbers), the API in `api_server.py`.
