# Answer-quality evaluation

The offline test suite proves KARAG is *safe* — nobody sees what they are not
cleared for. This directory measures whether it is *right*: real questions,
answered by a real model, checked against known answers. Every change to
retrieval, prompts or the model choice should be measured here first.

## What is in it

* `corpus/` — 15 documents of a pharmacy chain in Russian, Tajik and English:
  a cold-chain SOP and a general-storage SOP that look alike, payroll (HR
  only), a supplier contract (finance only), controlled substances
  (regulated), a store directory, an English infosec policy, a Tajik
  customer-service instruction, a product-code list, a Q2 report.
* `--stress` adds ~20 look-alikes a real knowledge base is full of: a
  400-line price list of near-identical codes (АМК-500, АМК-1250…), eight
  monthly reports next to the quarterly one, last year's payroll (marked
  void), another supplier's contract, six store passports.
* The testbench database (`testbench/build/apteka.db`, build it with
  `python testbench/build.py`) as a free-query skill, finance-cleared.
* `questions.json` — 63 questions with checkable answers:
  `fact` (doc look-ups, incl. exact codes, cross-language, Tajik), `leak`
  (a caller without clearance must not get the figure), `abstain` (not in the
  documents → say so), `data` / `hard-data` (SQL against the database, incl.
  period comparisons and shares), `hard-doc` (date arithmetic, old vs current
  policy, two documents at once) and `expert` (multi-step analysis, stacked
  rules, "September has no data yet").

Grading is deterministic: expected strings must appear, forbidden ones must
not, with numbers normalised ("4 200" = "4200", "27,4" = "27.4",
"94,582.90" = "94582.90"). It also records which documents reached the model,
which were cited, cost per answer and latency.

## Running it

```bash
set -a; source .env; set +a
PYTHONPATH=. .venv/bin/python evals/run_eval.py --stress --label mychange
PYTHONPATH=. .venv/bin/python evals/run_eval.py --stress --retrieval-only     # free: no model calls
PYTHONPATH=. .venv/bin/python evals/run_eval.py --stress --model claude-haiku-5-5 --effort medium
PYTHONPATH=. .venv/bin/python evals/run_eval.py --only code-amk,x-pay-stack
```

The platform is built in memory for the run — the real instance and its data
are never touched. Embeddings are cached in `evals/.cache/`, so a re-run only
pays for generation (about $0.40 for all 63 questions on Sonnet 5.5). Results
go to `evals/results/` (both git-ignored). Switches mirror the settings:
`--retrieval dense|hybrid`, `--contextual 0|1`, `--agentic 0|1`,
`--relative-floor`, `--min-score`, `--top-k`.

## What it showed (2026-11-24)

**Retrieval** (stress corpus, Sonnet 5.5 medium, 42 questions):

| Pipeline | Correct | Right doc reached the model | Cited sources that were right | Wrong-doc passages shown | $ / answer |
|---|---|---|---|---|---|
| before: vector only, 5 passages always | 41/42 | 97% | 77% | 3.3 | 0.0092 |
| after: hybrid + context + gate + search tool | **42/42** | **100%** | **82%** | **1.3** | **0.0073** |

**Model choice** (new pipeline, stress corpus; main set of 55 + expert tier
of 8 run twice):

| Model, effort | Main 55 | Expert 16 | Cited sources that were right | $ / answer | Median s |
|---|---|---|---|---|---|
| Sonnet 5.5, medium | 55/55 | 16/16 | 81% | 0.006 – 0.010 | 2.4 |
| Sonnet 5.5, low | 55/55 | 15/16 | 85% | 0.006 – 0.010 | 2.7 |
| Opus 5.5, low | 55/55 | 16/16 | 83% | 0.018 – 0.024 | 3.2 |
| Opus 5.5, medium | 55/55 | — | 82% | 0.018 | 4.1 |
| Haiku 5.5, medium | 55/55 | 16/16 | 79% | 0.0006 – 0.0008 | 2.2 |
| GPT-5.5 (fallback) | 54/55 | — | 97% | 0.008 | 2.8 |

Sonnet 5.5 at medium is the default: no misses, a third of Opus's price, and
server-side refusal fallback (Haiku 5.5 has none). Haiku 5.5 matched it on
these questions for a tenth of the price; this set does not grade long-form
reports, generated files or open-ended analysis, which is where the larger
model is expected to earn its price — measure those before switching.
