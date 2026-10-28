# Evaluation

_Generated 2026-10-28T16:45:49+00:00 by `tests/run_eval.py`._

## Setup

- **Cases:** 75 (25 handwritten by the project owner, 50 synthetic generated with Claude Opus 5.5 - each case file's Notes name the model that actually served the request, since one category fell back to Claude Opus 5 after a safety-classifier refusal), of which 15 are clean cases with no planted problem. Answer keys of the synthetic cases were audited automatically (see tests/README.md); case files live in `tests/cases/`.
- **Models:** Claude Haiku 5.5 (`claude-haiku-5-5`), Claude Sonnet 5.5 (`claude-sonnet-5-5`), Claude Opus 5.5 (`claude-opus-5-5`), Claude Fable 5.1 (`claude-fable-5-1`).
- **Repeats:** every case was checked 3 times per model, submitted through the Message Batches API (50% of standard prices). Effort `high`, max_tokens 16000, the same rules and JSON schema as the app, system prompt version `v1`.
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
| Claude Haiku 5.5 | 98% | 39% | 61% | 42% | 2.7 | 1.2 | 84% | 100% | 81% | $0.0013 | 225 / 225 |
| Claude Sonnet 5.5 | 99% | 48% | 52% | 23% | 1.8 | 0.5 | 29% | 96% | 81% | $0.013 | 225 / 225 |
| Claude Opus 5.5 | 100% | 50% | 50% | 30% | 1.7 | 0.7 | 56% | 100% | 85% | $0.022 | 143 / 225 |
| Claude Fable 5.1 | 99% | 50% | 50% | 24% | 1.8 | 0.5 | 22% | 100% | 81% | $0.066 | 146 / 225 |

## Results - handwritten cases

| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 97% | 53% | 47% | 33% | 2.4 | 1.3 | 100% | 100% | 95% | $0.0012 | 75 / 75 |
| Claude Sonnet 5.5 | 98% | 59% | 41% | 23% | 2.0 | 0.8 | 40% | 100% | 92% | $0.012 | 75 / 75 |
| Claude Opus 5.5 | 99% | 55% | 45% | 30% | 2.2 | 1.1 | 75% | 100% | 93% | $0.029 | 56 / 75 |
| Claude Fable 5.1 | 98% | 54% | 46% | 24% | 2.3 | 0.8 | 46% | 100% | 92% | $0.081 | 63 / 75 |

## Results - synthetic cases

| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 100% | 30% | 70% | 50% | 2.8 | 1.1 | 77% | 100% | 74% | $0.0014 | 150 / 150 |
| Claude Sonnet 5.5 | 100% | 40% | 60% | 23% | 1.8 | 0.3 | 23% | 93% | 76% | $0.014 | 150 / 150 |
| Claude Opus 5.5 | 100% | 44% | 56% | 30% | 1.4 | 0.5 | 40% | 100% | 80% | $0.018 | 87 / 150 |
| Claude Fable 5.1 | 100% | 44% | 56% | 22% | 1.5 | 0.3 | 0% | 100% | 74% | $0.059 | 83 / 150 |

## Latency and direct-call cost (sample)

Direct (non-batch) calls on the first five flawed handwritten cases; refused calls are excluded from the timing and counted separately.

| Model | Completed | Refused / failed | Mean | Min | Max | Mean cost / check (standard price) |
|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | 5 | 0 | 24 s | 18 s | 28 s | $0.0027 |
| Claude Sonnet 5.5 | 5 | 0 | 19 s | 17 s | 20 s | $0.031 |
| Claude Opus 5.5 | 3 | 2 | 42 s | 38 s | 50 s | $0.099 |
| Claude Fable 5.1 | 4 | 1 | 38 s | 33 s | 49 s | $0.175 |

## Per-rule recall (all cases)

Each cell is recall with (caught / planted) counted over that model's successful runs.

| Rule | Cases with rule planted | Claude Haiku 5.5 | Claude Sonnet 5.5 | Claude Opus 5.5 | Claude Fable 5.1 |
|---|---|---|---|---|---|
| R01 | 13 | 97% (38/39) | 100% (39/39) | 100% (22/22) | 100% (24/24) |
| R02 | 28 | 98% (82/84) | 99% (83/84) | 98% (58/59) | 98% (55/56) |
| R03 | 21 | 100% (63/63) | 100% (63/63) | 100% (45/45) | 96% (45/47) |
| R04 | 11 | 100% (33/33) | 97% (32/33) | 100% (24/24) | 100% (21/21) |
| R05 | 5 | 100% (15/15) | 100% (15/15) | 100% (12/12) | 100% (12/12) |
| R06 | 5 | 100% (15/15) | 100% (15/15) | 100% (9/9) | 93% (14/15) |
| R07 | 5 | 100% (15/15) | 100% (15/15) | 100% (11/11) | 100% (15/15) |
| R08 | 14 | 93% (39/42) | 93% (39/42) | 100% (20/20) | 100% (26/26) |
| R09 | 4 | 100% (12/12) | 100% (12/12) | - | 100% (3/3) |
| R10 | 2 | 100% (6/6) | 100% (6/6) | - | 100% (3/3) |
| R11 | 6 | 100% (18/18) | 100% (18/18) | 100% (7/7) | 100% (12/12) |
| R12 | 17 | 100% (51/51) | 100% (51/51) | 100% (34/34) | 100% (36/36) |

## False positives by severity (all cases)

| Model | Critical | Major | Minor |
|---|---|---|---|
| Claude Haiku 5.5 | 19 | 242 | 344 |
| Claude Sonnet 5.5 | 9 | 96 | 307 |
| Claude Opus 5.5 | 5 | 97 | 144 |
| Claude Fable 5.1 | 3 | 77 | 186 |

## Per-rule false positives (count of not-planted reports, all cases)

| Rule | Claude Haiku 5.5 | Claude Sonnet 5.5 | Claude Opus 5.5 | Claude Fable 5.1 |
|---|---|---|---|---|
| R01 | 100 | 70 | 45 | 52 |
| R02 | 35 | 14 | 0 | 3 |
| R03 | 83 | 49 | 39 | 34 |
| R04 | 62 | 58 | 34 | 35 |
| R05 | 44 | 14 | 9 | 11 |
| R06 | 10 | 7 | 8 | 6 |
| R07 | 13 | 12 | 11 | 9 |
| R08 | 41 | 28 | 8 | 11 |
| R09 | 11 | 10 | 0 | 0 |
| R10 | 6 | 1 | 0 | 0 |
| R11 | 63 | 44 | 21 | 20 |
| R12 | 137 | 105 | 71 | 85 |

## Failed runs

Failed runs are excluded from every metric above. 'Unknown rule IDs' counts findings that cite a rule outside R01-R12; they are ignored by the scoring.

| Model | Errors by type | Unknown rule IDs reported |
|---|---|---|
| Claude Haiku 5.5 | none | 0 |
| Claude Sonnet 5.5 | none | 0 |
| Claude Opus 5.5 | refusal: 82 | 0 |
| Claude Fable 5.1 | refusal: 79 | 0 |

### Refusals

A `refusal` is the model's safety classifier declining the request before any report is written (in our probes the category was `bio`, triggered by CRISPR knockout text). The Message Batches API does not accept the `fallbacks` parameter, so a refusal is a failed run here and costs only the input tokens. The app itself sends `fallbacks: "default"`, so a refused check is re-run on Anthropic's fallback model instead of failing. The **Refused** column in the README table is refusals / all runs.

- **Claude Haiku 5.5**: no refusals.
- **Claude Sonnet 5.5**: no refusals.
- **Claude Opus 5.5** refused 82 runs on 31 cases: hand_02 (1/3), hand_04 (3/3), hand_05 (3/3), hand_13 (3/3), hand_16 (3/3), hand_20 (3/3), hand_22 (3/3), syn_animal_03 (3/3), syn_animal_05 (2/3), syn_animal_06 (3/3), syn_animal_08 (1/3), syn_crispr_01 (3/3), syn_crispr_02 (3/3), syn_crispr_03 (3/3), syn_crispr_04 (3/3), syn_crispr_05 (3/3), syn_crispr_06 (3/3), syn_crispr_07 (3/3), syn_crispr_08 (3/3), syn_crispr_09 (3/3), syn_cuttag_01 (2/3), syn_cuttag_02 (2/3), syn_cuttag_06 (3/3), syn_cuttag_07 (2/3), syn_qpcr_07 (3/3), syn_rnai_01 (2/3), syn_rnai_03 (1/3), syn_rnai_04 (3/3), syn_rnai_06 (3/3), syn_rnai_08 (3/3), syn_rnai_09 (3/3)
- **Claude Fable 5.1** refused 79 runs on 29 cases: hand_05 (3/3), hand_13 (3/3), hand_16 (3/3), hand_19 (1/3), hand_22 (2/3), syn_animal_06 (3/3), syn_crispr_01 (3/3), syn_crispr_02 (3/3), syn_crispr_03 (3/3), syn_crispr_04 (3/3), syn_crispr_05 (3/3), syn_crispr_06 (3/3), syn_crispr_07 (3/3), syn_crispr_08 (3/3), syn_crispr_09 (3/3), syn_cuttag_01 (2/3), syn_cuttag_02 (3/3), syn_cuttag_06 (3/3), syn_cuttag_07 (3/3), syn_qpcr_05 (1/3), syn_qpcr_07 (3/3), syn_qpcr_09 (1/3), syn_rnai_04 (3/3), syn_rnai_06 (3/3), syn_rnai_07 (3/3), syn_rnai_08 (3/3), syn_rnai_09 (3/3), syn_western_03 (3/3), syn_western_07 (3/3)

## Reproducing

```bash
python tests/run_eval.py estimate            # cost estimate, nothing is sent
python tests/run_eval.py submit              # submit one batch per model
python tests/run_eval.py collect             # fetch finished batches, score, write this file
python tests/run_eval.py latency --n 5       # optional: direct-call timing sample
```

On Windows, `collect_results.bat` runs the collect step.

<!-- compare-start -->
## Comparison: baseline vs prompt-v2 vs prompt-v3

_Same 75 cases and 3 repeats; only the system prompt and the 'Satisfied when / Not a finding' lines in rules.md changed between runs. Full results of the tagged runs: [docs/eval-prompt-v2.md](eval-prompt-v2.md), [docs/eval-prompt-v3.md](eval-prompt-v3.md)._

### Claude Sonnet 5.5: prompt v1 vs prompt v2 (prompt-v2) vs prompt v3 (prompt-v3)

| Metric | prompt v1 | prompt v2 (prompt-v2) | prompt v3 (prompt-v3) |
|---|---|---|---|
| Recall | 99% | 91% | 97% |
| Precision | 48% | 91% | 91% |
| FP rate (all) | 52% | 9% | 9% |
| FP rate (critical/major) | 23% | 6% | 6% |
| FP per run (all) | 1.8 | 0.2 | 0.2 |
| FP per run (critical/major) | 0.5 | 0.1 | 0.1 |
| Clean cases flagged (critical/major) | 29% | 0% | 0% |
| Clean cases flagged (any) | 96% | 0% | 0% |
| Consistency | 81% | 93% | 95% |
| Refused | 0% | 0% | 0% |
| Mean cost / check (batch) | $0.013 | $0.0095 | $0.0099 |
| Runs ok / total | 225 / 225 | 225 / 225 | 225 / 225 |

| Subset / metric | prompt v1 | prompt v2 (prompt-v2) | prompt v3 (prompt-v3) |
|---|---|---|---|
| handwritten / recall | 98% | 91% | 97% |
| handwritten / FP rate (critical/major) | 23% | 9% | 8% |
| handwritten / clean cases flagged (critical/major) | 40% | 0% | 0% |
| synthetic / recall | 100% | 92% | 97% |
| synthetic / FP rate (critical/major) | 23% | 3% | 3% |
| synthetic / clean cases flagged (critical/major) | 23% | 0% | 0% |

<!-- compare-end -->
