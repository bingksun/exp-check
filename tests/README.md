# Evaluation of exp-check

This folder holds the test cases and the scripts that measure how well different Claude
models apply `rules.md`. Results are written to [`docs/eval.md`](../docs/eval.md) and a
summary table in the main README.

## Case files (`cases/*.md`)

One file per case. The answer key is a list of rule IDs from `rules.md`:

```
---
id: hand_01
source: handwritten         # or synthetic
category: RNAi
title: short description
answer: R02, R06, R07       # planted problems; write 无 (or none) for a clean case
tolerated: R03              # arguably present but not planted: counted neither as hit nor as false positive
---

## Text

The English text that gets pasted into exp-check.

## Notes

- Anything useful: the original answer, mapping decisions, points that must not be flagged.
```

To add a case, copy a file, change `id` (must be unique and match the file name), the
text and the answer line. `hand_*.md` were written by the project owner; `syn_*.md` were
generated with Claude Opus 5.5 by `generate_cases.py` and should be reviewed before their
answer keys are trusted.

## Scoring

Scores are computed by rule ID only, with no model acting as judge. For every check the
set of rule IDs in the report's findings is compared with the case's answer:

- recall: planted rules reported / planted rules
- false-positive rate: reported rules that were not planted / reported rules
- clean cases wrongly flagged: share of checks on clean cases with a critical or major finding
- consistency: how similar the reported rule sets are across the three repeats of a case
- cost: from the API's token usage at batch prices

## Running it

```bash
python tests/run_eval.py estimate            # token counts and cost estimate; sends nothing
python tests/run_eval.py submit              # one Message Batch per model, 3 repeats per case
python tests/run_eval.py collect             # fetch finished batches, score, write docs/eval.md + README table
python tests/run_eval.py latency --n 5       # optional: direct calls to measure response time
python tests/generate_cases.py               # regenerate synthetic cases (skips categories that exist)
```

On Windows, double-click `collect_results.bat` in the project folder to run the collect step.
Batch IDs are kept in `tests/results/batches.json`; raw model outputs land in
`tests/results/raw_<model>.jsonl` (not committed) and the scored summary in
`tests/results/summary.json`.
