"""Shared code for the exp-check evaluation.

Case files, the model/price table, request building, scoring and report writing.
Used by run_eval.py and generate_cases.py.

Case file format (tests/cases/*.md):

    ---
    id: hand_01
    source: handwritten          # or: synthetic
    category: RNAi
    title: short description
    answer: R02, R06, R07        # rules that are planted in the text; "无" / "none" = clean case
    tolerated: R03               # rules that are arguably present but not planted: neither hit nor false positive
    ---

    ## Text

    <the English text that is pasted into exp-check>

    ## Notes

    - free-form notes (original answer, mapping decisions, things that must NOT be flagged)
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import checker  # noqa: E402  - the app's own prompt, schema and config

CASES_DIR = TESTS_DIR / "cases"
RESULTS_DIR = TESTS_DIR / "results"
DOCS_EVAL = ROOT / "docs" / "eval.md"
README = ROOT / "README.md"

ALL_RULES = [f"R{i:02d}" for i in range(1, 13)]
RULE_RE = re.compile(r"\bR0?(\d{1,2})\b")   # accepts R07 and R7; normalise with norm_rule()
SEV_RANK = {"critical": 3, "major": 2, "minor": 1}


def norm_rule(digits: str) -> str:
    return f"R{int(digits):02d}"

# Prices in USD per million tokens at the standard (non-batch) rate. Batch requests cost half.
# Edit this table if Anthropic changes prices.
MODELS = {
    "haiku55": {
        "id": "claude-haiku-5-5",
        "label": "Claude Haiku 5.5",
        "price": {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
    },
    "sonnet55": {
        "id": "claude-sonnet-5-5",
        "label": "Claude Sonnet 5.5",
        "price": {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
    },
    "opus55": {
        "id": "claude-opus-5-5",
        "label": "Claude Opus 5.5",
        "price": {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20},
    },
    "fable51": {
        "id": "claude-fable-5-1",
        "label": "Claude Fable 5.1",
        "price": {"input": 10.00, "output": 50.00, "cache_write": 12.50, "cache_read": 0.25},
    },
}
BATCH_DISCOUNT = 0.5


# --------------------------------------------------------------------------- cases


@dataclass
class Case:
    id: str
    source: str
    category: str
    title: str
    answer: set
    tolerated: set
    text: str
    path: Path

    @property
    def clean(self) -> bool:
        return not self.answer


def parse_rule_list(value: str) -> set:
    v = (value or "").strip()
    if v.lower() in ("", "无", "none", "-", "n/a"):
        return set()
    ids = {norm_rule(m) for m in RULE_RE.findall(v)}
    bad = ids - set(ALL_RULES)
    if bad:
        raise ValueError(f"unknown rule ids {sorted(bad)} in {value!r}")
    if not ids:
        raise ValueError(f"no rule ids found in {value!r} (write e.g. 'R02, R06' or '无')")
    return ids


FRONT_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n(.*)\Z", re.S)
SECTION_RE = re.compile(r"^## (Text|Notes)\s*$", re.M | re.I)   # only these two headings split sections


def _split_sections(body: str) -> dict:
    parts = {}
    marks = list(SECTION_RE.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        parts[m.group(1).lower()] = body[m.end():end]
    return parts


def load_cases(cases_dir: Path = CASES_DIR) -> list:
    cases = []
    for path in sorted(cases_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8-sig")
        m = FRONT_RE.match(raw)
        if not m:
            raise ValueError(f"{path.name}: missing '---' front matter")
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                v = re.split(r"\s+#", v, 1)[0].strip()   # drop inline "# comments"
                meta[k.strip().lower()] = v
        if "answer" not in meta:
            raise ValueError(f"{path.name}: missing 'answer:' line (write 无 for a clean case)")
        if meta.get("source") not in ("handwritten", "synthetic"):
            raise ValueError(f"{path.name}: source must be 'handwritten' or 'synthetic' (got {meta.get('source')!r})")
        text = _split_sections(m.group(2)).get("text", "").strip()
        if not text:
            raise ValueError(f"{path.name}: no '## Text' section")
        cases.append(
            Case(
                id=meta.get("id") or path.stem,
                source=meta.get("source", "unknown"),
                category=meta.get("category", "unknown"),
                title=meta.get("title", ""),
                answer=parse_rule_list(meta.get("answer", "")),
                tolerated=parse_rule_list(meta.get("tolerated", "")),
                text=text,
                path=path,
            )
        )
    ids = [c.id for c in cases]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        raise ValueError(f"duplicate case ids: {sorted(dups)}")
    return cases


def write_case_file(path: Path, *, id: str, source: str, category: str, title: str,
                    answer: set, tolerated: set, text: str, notes: list) -> None:
    def fmt(s):
        return ", ".join(sorted(s)) if s else "无"

    lines = [
        "---",
        f"id: {id}",
        f"source: {source}",
        f"category: {category}",
        f"title: {title}",
        f"answer: {fmt(answer)}",
        f"tolerated: {fmt(tolerated)}",
        "---",
        "",
        "## Text",
        "",
        text.strip(),
        "",
        "## Notes",
        "",
    ]
    lines += [f"- {n}" for n in notes] if notes else ["-"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- requests


def build_params(model_id: str, case: Case, cfg: dict, rules_text: str) -> dict:
    """The exact request exp-check sends, minus the fallback beta (rejected by the Batch API)."""
    return {
        "model": model_id,
        "max_tokens": int(cfg["max_tokens"]),
        "system": checker.build_system(rules_text),
        "messages": [{"role": "user", "content": checker.build_user_message(case.text, "Auto-detect")}],
        "output_config": {
            "effort": cfg["effort"],
            "format": {"type": "json_schema", "schema": checker.REPORT_SCHEMA},
        },
    }


def custom_id(model_key: str, case_id: str, rep: int) -> str:
    cid = f"{model_key}__{case_id}__r{rep}"
    if "__" in case_id or len(cid) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
        raise ValueError(
            f"case id {case_id!r} cannot be used in a Batch custom_id (letters, digits, '-' and single '_' only, "
            f"no '__', total length <= 64): {cid!r}"
        )
    return cid


def parse_custom_id(cid: str):
    model_key, rest = cid.split("__", 1)
    case_id, rep = rest.rsplit("__", 1)
    return model_key, case_id, int(rep[1:])


# --------------------------------------------------------------------------- runs and scoring


@dataclass
class Run:
    custom_id: str
    model_key: str
    case_id: str
    rep: int
    status: str            # ok | error | refusal | max_tokens | parse_error
    rules: dict            # rule id -> severity (findings in the report)
    usage: dict = field(default_factory=dict)
    stop_reason: str | None = None
    error: str | None = None
    latency_s: float | None = None
    unknown_rules: list = field(default_factory=list)   # rule ids outside R01-R12 that the model reported


def extract_rules(report: dict):
    """Returns (rule id -> worst severity, list of unknown rule ids) from a report's findings."""
    out, unknown = {}, []
    for f in report.get("findings", []) or []:
        m = RULE_RE.search(str(f.get("rule_id", ""))) or RULE_RE.search(str(f.get("title", "")))
        if not m:
            continue
        rid = norm_rule(m.group(1))
        if rid not in ALL_RULES:
            unknown.append(rid)
            continue
        sev = str(f.get("severity", "")).lower()
        if sev not in SEV_RANK:
            sev = "major"
        if rid not in out or SEV_RANK[sev] > SEV_RANK[out[rid]]:
            out[rid] = sev
    return out, unknown


def usage_from_message(msg) -> dict:
    u = getattr(msg, "usage", None)
    if u is None:
        return {}
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def raw_from_message(cid: str, msg, latency_s: float | None = None) -> dict:
    """One raw-result record (what gets written to raw_<model>.jsonl) from a Message object."""
    text = next((b.text for b in msg.content if b.type == "text"), "")
    return {
        "custom_id": cid,
        "result_type": "succeeded",
        "model": getattr(msg, "model", None),
        "stop_reason": getattr(msg, "stop_reason", None),
        "usage": usage_from_message(msg),
        "text": text,
        "latency_s": latency_s,
    }


def run_from_raw(raw: dict) -> Run:
    model_key, case_id, rep = parse_custom_id(raw["custom_id"])
    run = Run(
        custom_id=raw["custom_id"], model_key=model_key, case_id=case_id, rep=rep,
        status="ok", rules={}, usage=raw.get("usage") or {},
        stop_reason=raw.get("stop_reason"), error=raw.get("error"), latency_s=raw.get("latency_s"),
    )
    if raw.get("result_type") != "succeeded":
        run.status = "error"
        return run
    if run.stop_reason == "refusal":
        run.status = "refusal"
        return run
    if run.stop_reason == "max_tokens":
        run.status = "max_tokens"
        return run
    try:
        report = json.loads(raw.get("text") or "")
    except (json.JSONDecodeError, TypeError):
        run.status = "parse_error"
        return run
    if not isinstance(report, dict):
        run.status = "parse_error"
        return run
    run.rules, run.unknown_rules = extract_rules(report)
    return run


def usage_cost(usage: dict, price: dict, batch: bool = True) -> float:
    f = BATCH_DISCOUNT if batch else 1.0
    return f * (
        (usage.get("input_tokens") or 0) * price["input"]
        + (usage.get("output_tokens") or 0) * price["output"]
        + (usage.get("cache_creation_input_tokens") or 0) * price["cache_write"]
        + (usage.get("cache_read_input_tokens") or 0) * price["cache_read"]
    ) / 1e6


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def metrics(runs: list, cases: dict, price: dict, batch: bool = True) -> dict:
    """Aggregate metrics for one model over a list of runs.

    recall            = planted problems caught / planted problems (flawed cases only)
    precision         = reported rules that were planted / reported rules (tolerated rules excluded)
    fp_rate           = reported rules that were NOT planted / reported rules (tolerated excluded)
    fp_per_run        = mean number of not-planted rules reported per run
    clean_flagged_any = share of clean-case runs with at least one finding (tolerated excluded)
    clean_flagged_major = share of clean-case runs with a critical or major finding
    consistency       = mean pairwise Jaccard similarity of the rule sets across repeats of a case
    """
    ok = [r for r in runs if r.status == "ok"]
    planted = caught = reported = fp = 0
    reported_major = fp_major = 0
    fp_by_sev = {"critical": 0, "major": 0, "minor": 0}
    clean_n = clean_any = clean_major = 0
    for r in ok:
        c = cases[r.case_id]
        P, A, T = set(r.rules), c.answer, c.tolerated
        scored = P - T
        if A:
            planted += len(A)
            caught += len(P & A)
        reported += len(scored)
        fp += len(scored - A)
        for rule in scored:
            sev = r.rules[rule]
            if SEV_RANK[sev] >= 2:
                reported_major += 1
            if rule not in A:
                fp_by_sev[sev] += 1
                if SEV_RANK[sev] >= 2:
                    fp_major += 1
        if not A:
            clean_n += 1
            if scored:
                clean_any += 1
            if any(SEV_RANK[r.rules[x]] >= 2 for x in scored):
                clean_major += 1
    errors = {}
    refused_cases = {}
    for r in runs:
        if r.status != "ok":
            errors[r.status] = errors.get(r.status, 0) + 1
        if r.status == "refusal":
            refused_cases[r.case_id] = refused_cases.get(r.case_id, 0) + 1
    costs = [usage_cost(r.usage, price, batch) for r in runs if r.usage]
    by_case = {}
    for r in ok:
        by_case.setdefault(r.case_id, []).append(frozenset(r.rules))
    jacc = []
    for sets in by_case.values():
        for a, b in combinations(sets, 2):
            jacc.append(1.0 if not a and not b else len(a & b) / len(a | b))
    return {
        "runs": len(runs),
        "ok": len(ok),
        "errors": errors,
        "planted": planted,
        "caught": caught,
        "reported": reported,
        "false_positives": fp,
        "recall": caught / planted if planted else None,
        "precision": (reported - fp) / reported if reported else None,
        "fp_rate": fp / reported if reported else None,
        "fp_per_run": fp / len(ok) if ok else None,
        "fp_rate_major": fp_major / reported_major if reported_major else None,
        "fp_per_run_major": fp_major / len(ok) if ok else None,
        "fp_by_severity": fp_by_sev,
        "refused_cases": dict(sorted(refused_cases.items())),
        "clean_runs": clean_n,
        "clean_flagged_any": clean_any / clean_n if clean_n else None,
        "clean_flagged_major": clean_major / clean_n if clean_n else None,
        "mean_cost_usd": _mean(costs),
        "total_cost_usd": sum(costs),
        "mean_output_tokens": _mean([r.usage.get("output_tokens") for r in runs if r.usage]),
        "mean_latency_s": _mean([r.latency_s for r in runs]),
        "consistency": _mean(jacc),
        "unknown_rule_reports": sum(len(r.unknown_rules) for r in ok),
        "refusal_rate": errors.get("refusal", 0) / len(runs) if runs else None,
    }


def per_rule(runs: list, cases: dict) -> dict:
    out = {}
    ok = [r for r in runs if r.status == "ok"]
    for rule in ALL_RULES:
        planted = caught = fp = 0
        for r in ok:
            c = cases[r.case_id]
            if rule in c.answer:
                planted += 1
                if rule in r.rules:
                    caught += 1
            elif rule in r.rules and rule not in c.tolerated:
                fp += 1
        out[rule] = {"planted": planted, "caught": caught, "false_positives": fp,
                     "recall": caught / planted if planted else None}
    return out


def score_all(runs_by_model: dict, cases: list, latency: dict | None = None) -> dict:
    """runs_by_model: model_key -> list[Run] (batch runs). latency: model_key -> list[Run] (direct runs)."""
    case_map = {c.id: c for c in cases}
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_cases": len(cases),
        "n_handwritten": sum(c.source == "handwritten" for c in cases),
        "n_synthetic": sum(c.source == "synthetic" for c in cases),
        "n_clean": sum(c.clean for c in cases),
        "planted_cases": {rule: sum(1 for c in cases if rule in c.answer) for rule in ALL_RULES},
        "models": {},
    }
    for mk, runs in runs_by_model.items():
        price = MODELS[mk]["price"]
        entry = {"label": MODELS[mk]["label"], "model_id": MODELS[mk]["id"]}
        entry["all"] = metrics(runs, case_map, price)
        for src in ("handwritten", "synthetic"):
            sub = [r for r in runs if case_map[r.case_id].source == src]
            entry[src] = metrics(sub, case_map, price) if sub else None
        entry["per_rule"] = per_rule(runs, case_map)
        if latency and latency.get(mk):
            lat_all = latency[mk]
            lat_runs = [r for r in lat_all if r.status == "ok"]   # refusals return in a second: exclude them
            entry["latency"] = {
                "n": len(lat_runs),
                "n_failed": len(lat_all) - len(lat_runs),
                "mean_s": _mean([r.latency_s for r in lat_runs]),
                "min_s": min((r.latency_s for r in lat_runs if r.latency_s is not None), default=None),
                "max_s": max((r.latency_s for r in lat_runs if r.latency_s is not None), default=None),
                "mean_cost_usd_direct": _mean([usage_cost(r.usage, price, batch=False) for r in lat_runs if r.usage]),
            }
        else:
            entry["latency"] = None
        summary["models"][mk] = entry
    return summary


# --------------------------------------------------------------------------- report writing


def pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def money(x) -> str:
    return "-" if x is None else f"${x:.4f}" if x < 0.01 else f"${x:.3f}"


def secs(x) -> str:
    return "-" if x is None else f"{x:.0f} s"


def num(x, nd=1) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def _metrics_table(summary: dict, key: str) -> list:
    rows = [
        "| Model | Recall | Precision | FP rate (all) | FP rate (critical/major) | FP per run (all) | FP per run (critical/major) | Clean cases flagged (critical/major) | Clean cases flagged (any) | Consistency | Mean cost / check (batch) | Runs ok / total |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for mk, e in summary["models"].items():
        m = e.get(key)
        if not m:
            rows.append(f"| {e['label']} | - | - | - | - | - | - | - | - | - | - | 0 / 0 |")
            continue
        rows.append(
            f"| {e['label']} | {pct(m['recall'])} | {pct(m['precision'])} | {pct(m['fp_rate'])} | "
            f"{pct(m.get('fp_rate_major'))} | {num(m['fp_per_run'])} | {num(m.get('fp_per_run_major'))} | "
            f"{pct(m['clean_flagged_major'])} | {pct(m['clean_flagged_any'])} | "
            f"{pct(m['consistency'])} | {money(m['mean_cost_usd'])} | {m['ok']} / {m['runs']} |"
        )
    return rows


def compact_table(summary: dict) -> list:
    rows = [
        "| Model | Recall | False positives (all) | False positives (critical/major) | Clean cases wrongly flagged | Refused | Mean cost / check (batch) | Mean latency (direct) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mk, e in summary["models"].items():
        m = e["all"]
        lat = e.get("latency") or {}
        rows.append(
            f"| {e['label']} | {pct(m['recall'])} | {pct(m['fp_rate'])} | {pct(m.get('fp_rate_major'))} | "
            f"{pct(m['clean_flagged_major'])} | {pct(m.get('refusal_rate'))} | {money(m['mean_cost_usd'])} | "
            f"{secs(lat.get('mean_s'))} |"
        )
    return rows


def write_eval_md(summary: dict, reps: int, cfg: dict, path: Path = DOCS_EVAL) -> None:
    s = summary
    lines = [
        "# Evaluation",
        "",
        f"_Generated {s['generated_at']} by `tests/run_eval.py`._",
        "",
        "## Setup",
        "",
        f"- **Cases:** {s['n_cases']} ({s['n_handwritten']} handwritten by the project owner, "
        f"{s['n_synthetic']} synthetic generated with Claude Opus 5.5 - each case file's Notes name the model "
        f"that actually served the request, since one category fell back to Claude Opus 5 after a safety-classifier "
        f"refusal), of which {s['n_clean']} are clean cases with no planted problem. Answer keys of the synthetic "
        "cases were audited automatically (see tests/README.md); case files live in `tests/cases/`.",
        f"- **Models:** " + ", ".join(f"{e['label']} (`{e['model_id']}`)" for e in s["models"].values()) + ".",
        f"- **Repeats:** every case was checked {reps} times per model, submitted through the Message Batches API "
        f"(50% of standard prices). Effort `{cfg['effort']}`, max_tokens {cfg['max_tokens']}, the same rules and "
        f"JSON schema as the app, system prompt version `{s.get('prompt_version', 'v1')}`.",
        "- **Scoring:** by rule ID only, no model-as-judge. Each case file lists the planted rules (the answer key) "
        "and optionally *tolerated* rules that are arguably present but were not planted; tolerated rules count "
        "neither as hits nor as false positives.",
        "",
        "## Metric definitions",
        "",
        "- **Recall** - planted problems that were reported / all planted problems (flawed cases only).",
        "- **Precision** - reported rules that were planted / all reported rules.",
        "- **False-positive (FP) rate (all)** - reported rules that were *not* planted / all reported rules, "
        "whatever severity the model gave them.",
        "- **FP rate (critical/major)** - the same ratio counting only findings the model rated critical or "
        "major. Most not-planted findings are rated *minor* (typically 'catalogue number / sequence not listed', "
        "R12), so this column is the better measure of reports that would actually mislead a user.",
        "- **FP per run** - mean number of not-planted rules reported per check (all severities, and "
        "critical/major only).",
        "- **Clean cases flagged** - share of checks on clean cases that reported at least one critical/major "
        "finding (primary) or any finding at all (strict).",
        "- **Consistency** - mean pairwise Jaccard similarity of the reported rule sets across the repeats of a case "
        "(100% = identical every time).",
        "- **Mean cost / check** - from the token usage returned by the API, at batch prices "
        "(cache reads and writes included).",
        "- **Latency** - wall-clock seconds of direct (non-batch) calls on a small sample; the Batch API does not "
        "report per-request timing.",
        "",
        "## Results - all cases",
        "",
        *_metrics_table(s, "all"),
        "",
        "## Results - handwritten cases",
        "",
        *_metrics_table(s, "handwritten"),
        "",
        "## Results - synthetic cases",
        "",
        *_metrics_table(s, "synthetic"),
        "",
        "## Latency and direct-call cost (sample)",
        "",
        "Direct (non-batch) calls on the first five flawed handwritten cases; refused calls are excluded from the "
        "timing and counted separately.", "",
        "| Model | Completed | Refused / failed | Mean | Min | Max | Mean cost / check (standard price) |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in s["models"].values():
        lat = e.get("latency")
        if lat:
            lines.append(
                f"| {e['label']} | {lat['n']} | {lat.get('n_failed', 0)} | {secs(lat['mean_s'])} | "
                f"{secs(lat['min_s'])} | {secs(lat['max_s'])} | {money(lat['mean_cost_usd_direct'])} |"
            )
        else:
            lines.append(f"| {e['label']} | 0 | 0 | - | - | - | - |")
    lines += ["", "## Per-rule recall (all cases)", "",
              "Each cell is recall with (caught / planted) counted over that model's successful runs.", "",
              "| Rule | Cases with rule planted | " + " | ".join(e["label"] for e in s["models"].values()) + " |",
              "|---|---|" + "---|" * len(s["models"])]
    for rule in ALL_RULES:
        n_cases = s.get("planted_cases", {}).get(rule, "-")
        cells = " | ".join(
            f"{pct(p['recall'])} ({p['caught']}/{p['planted']})" if p["planted"] else "-"
            for p in (e["per_rule"][rule] for e in s["models"].values())
        )
        lines.append(f"| {rule} | {n_cases} | {cells} |")
    lines += ["", "## False positives by severity (all cases)", "",
              "| Model | Critical | Major | Minor |", "|---|---|---|---|"]
    for e in s["models"].values():
        b = e["all"].get("fp_by_severity") or {}
        lines.append(f"| {e['label']} | {b.get('critical', 0)} | {b.get('major', 0)} | {b.get('minor', 0)} |")
    lines += ["", "## Per-rule false positives (count of not-planted reports, all cases)", "",
              "| Rule | " + " | ".join(e["label"] for e in s["models"].values()) + " |",
              "|---|" + "---|" * len(s["models"])]
    for rule in ALL_RULES:
        cells = " | ".join(str(e["per_rule"][rule]["false_positives"]) for e in s["models"].values())
        lines.append(f"| {rule} | {cells} |")
    lines += ["", "## Failed runs", "",
              "Failed runs are excluded from every metric above. 'Unknown rule IDs' counts findings that cite a rule "
              "outside R01-R12; they are ignored by the scoring.", "",
              "| Model | Errors by type | Unknown rule IDs reported |", "|---|---|---|"]
    for e in s["models"].values():
        errs = e["all"]["errors"]
        lines.append(f"| {e['label']} | {', '.join(f'{k}: {v}' for k, v in errs.items()) if errs else 'none'} | "
                     f"{e['all'].get('unknown_rule_reports', 0)} |")
    lines += [
        "",
        "### Refusals",
        "",
        "A `refusal` is the model's safety classifier declining the request before any report is written "
        "(in our probes the category was `bio`, triggered by CRISPR knockout text). The Message Batches API does "
        "not accept the `fallbacks` parameter, so a refusal is a failed run here and costs only the input tokens. "
        "The app itself sends `fallbacks: \"default\"`, so a refused check is re-run on Anthropic's fallback model "
        "instead of failing. The **Refused** column in the README table is refusals / all runs.",
        "",
    ]
    for e in s["models"].values():
        rc = e["all"].get("refused_cases") or {}
        if rc:
            lines.append(f"- **{e['label']}** refused {sum(rc.values())} runs on {len(rc)} cases: " +
                         ", ".join(f"{cid} ({n}/{s.get('reps', 3)})" for cid, n in rc.items()))
        else:
            lines.append(f"- **{e['label']}**: no refusals.")
    lines += [
        "",
        "## Reproducing",
        "",
        "```bash",
        "python tests/run_eval.py estimate            # cost estimate, nothing is sent",
        "python tests/run_eval.py submit              # submit one batch per model",
        "python tests/run_eval.py collect             # fetch finished batches, score, write this file",
        "python tests/run_eval.py latency --n 5       # optional: direct-call timing sample",
        "```",
        "",
        "On Windows, `collect_results.bat` runs the collect step.",
        "",
    ]
    text = "\n".join(lines)
    # Keep a comparison block written earlier by `run_eval.py compare` when the file is regenerated.
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if COMPARE_START in old and COMPARE_END in old:
            block = old.split(COMPARE_START, 1)[1].split(COMPARE_END, 1)[0]
            text = text.rstrip("\n") + "\n\n" + COMPARE_START + block + COMPARE_END + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


README_START = "<!-- eval-table-start -->"
README_END = "<!-- eval-table-end -->"
README_COMPARE_START = "<!-- eval-compare-start -->"
README_COMPARE_END = "<!-- eval-compare-end -->"
COMPARE_START = "<!-- compare-start -->"
COMPARE_END = "<!-- compare-end -->"


def update_readme(summary: dict, path: Path = README) -> bool:
    text = path.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return False
    block = "\n".join(
        [README_START, "", *compact_table(summary), "",
         f"_{summary['n_cases']} cases, {summary.get('reps', 3)} repeats per model, batch prices. Full results and metric definitions "
         "in [docs/eval.md](docs/eval.md)._", README_END]
    )
    pre, rest = text.split(README_START, 1)
    _, post = rest.split(README_END, 1)
    path.write_text(pre + block + post, encoding="utf-8")
    return True
