# Evaluation

_Generated 2026-10-28T17:09:34+00:00 by `tests/run_eval.py`._

## Setup

- **Cases:** 75 (25 handwritten by the project owner, 50 synthetic generated with Claude Opus 5.5 - each case file's Notes name the model that actually served the request, since one category fell back to Claude Opus 5 after a safety-classifier refusal), of which 15 are clean cases with no planted problem. Answer keys of the synthetic cases were audited automatically (see tests/README.md); case files live in `tests/cases/`.
- **Models:** Claude Sonnet 5.5 (`claude-sonnet-5-5`).
- **Repeats:** every case was checked 3 times per model, submitted through the Message Batches API (50% of standard prices). Effort `high`, max_tokens 16000, the same rules and JSON schema as the app, system prompt version `v2`.
- **Scoring:** by rule ID only, no model-as-judge. Each case file lists the planted rules (the answer key) and optionally *tolerated* rules that are arguably present but were not planted; tolerated rules count neither as hits nor as false positives.

## Metric definitions

- **Recall** - planted problems that were reported / all planted problems (flawed cases only).
- **Precision** - reported rules that were planted / all reported rules.
- **False-positive (FP) rate (all)** - reported rules that were *not* planted / all reported rules, whatever severity the model gave them.
- **FP rate (critical/major)** - the same ratio counting only findings the model rated critical or major. Most not-planted findings are rated *minor* (typically 'catalogue number / sequence not listed', R12), so this column is the better measure of reports that would actually mislead a user.
- **FP per run** - mean number of not-planted rules reported per check (all severities, and critical/major only).
- **Clean cases flagged** - share of checks on clean cases that reported at least one critical/major finding (primary) or any finding at all (strict).
- **Consistency** - mean pairwise Jaccard similarity of the reported rule sets across the repeats of a case (100% = identical every time).
- **Mean cost / check** - from the token usage returned by the API, at batch prices (cache reads and writes included).
- **Latency** - wall-clock seconds of direct (non-batch) calls on a small sample; the Batch API does not report per-request timing.

## Results - all cases

| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 91% | 91% | 9% | 6% | 0.2 | 0.1 | 0% | 0% | 93% | $0.0095 | 225 / 225 |

## Results - handwritten cases

| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 91% | 89% | 11% | 9% | 0.3 | 0.3 | 0% | 0% | 93% | $0.0091 | 75 / 75 |

## Results - synthetic cases

| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 92% | 95% | 5% | 3% | 0.1 | 0.0 | 0% | 0% | 93% | $0.0097 | 150 / 150 |

## Latency and direct-call cost (sample)

Direct (non-batch) calls on the first five flawed handwritten cases; refused calls are excluded from the timing and counted separately.

| Model | Completed | Refused / failed | Mean | Min | Max | Mean cost / check (standard price) |
|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 0 | 0 | - | - | - | - |

## Per-rule recall (all cases)

Each cell is recall with (caught / planted) counted over that model's successful runs.

| Rule | Cases with rule planted | Claude Sonnet 5.5 |
|---|---|---|
| R01 | 13 | 77% (30/39) |
| R02 | 28 | 95% (80/84) |
| R03 | 21 | 95% (60/63) |
| R04 | 11 | 82% (27/33) |
| R05 | 5 | 93% (14/15) |
| R06 | 5 | 100% (15/15) |
| R07 | 5 | 100% (15/15) |
| R08 | 14 | 100% (42/42) |
| R09 | 4 | 100% (12/12) |
| R10 | 2 | 100% (6/6) |
| R11 | 6 | 72% (13/18) |
| R12 | 17 | 86% (44/51) |

## False positives by severity (all cases)

| Model | Critical | Major | Minor |
|---|---|---|---|
| Claude Sonnet 5.5 | 8 | 16 | 10 |

## Per-rule false positives (count of not-planted reports, all cases)

| Rule | Claude Sonnet 5.5 |
|---|---|
| R01 | 6 |
| R02 | 0 |
| R03 | 0 |
| R04 | 1 |
| R05 | 0 |
| R06 | 0 |
| R07 | 1 |
| R08 | 3 |
| R09 | 0 |
| R10 | 0 |
| R11 | 4 |
| R12 | 19 |

## Failed runs

Failed runs are excluded from every metric above. 'Unknown rule IDs' counts findings that cite a rule outside R01-R12; they are ignored by the scoring.

| Model | Errors by type | Unknown rule IDs reported |
|---|---|---|
| Claude Sonnet 5.5 | none | 0 |

### Refusals

A `refusal` is the model's safety classifier declining the request before any report is written (in our probes the category was `bio`, triggered by CRISPR knockout text). The Message Batches API does not accept the `fallbacks` parameter, so a refusal is a failed run here and costs only the input tokens. The app itself sends `fallbacks: "default"`, so a refused check is re-run on Anthropic's fallback model instead of failing. The **Refused** column in the README table is refusals / all runs.

- **Claude Sonnet 5.5**: no refusals.

## Reproducing

```bash
python tests/run_eval.py estimate            # cost estimate, nothing is sent
python tests/run_eval.py submit              # submit one batch per model
python tests/run_eval.py collect             # fetch finished batches, score, write this file
python tests/run_eval.py latency --n 5       # optional: direct-call timing sample
```

On Windows, `collect_results.bat` runs the collect step.
