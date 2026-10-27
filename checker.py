"""Core logic for exp-check: load config and rules, call the Anthropic API, parse the report.

The Streamlit UI (app.py) imports this module. Nothing here depends on Streamlit, so the
same functions could later be used from a command line or a test script.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

import anthropic
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "model": "claude-sonnet-5-5",
    "effort": "high",
    "max_tokens": 16000,
    "rules_file": "rules.md",
}

SEVERITIES = ("critical", "major", "minor")


class CheckError(Exception):
    """A problem the user can act on (missing key, bad config, API error)."""


# --------------------------------------------------------------------------- config / rules


def load_config() -> dict:
    """Read config.toml; fall back to defaults for anything missing."""
    cfg = dict(DEFAULT_CONFIG)
    path = ROOT / "config.toml"
    if path.exists():
        with open(path, "rb") as f:
            cfg.update(tomllib.load(f))
    if cfg["effort"] not in ("low", "medium", "high"):
        raise CheckError(
            f"config.toml: effort must be 'low', 'medium' or 'high' (got {cfg['effort']!r})."
        )
    return cfg


def load_rules(cfg: dict) -> str:
    path = ROOT / cfg["rules_file"]
    if not path.exists():
        raise CheckError(f"Rules file not found: {path.name}. Check 'rules_file' in config.toml.")
    return path.read_text(encoding="utf-8")


def count_rules(rules_text: str) -> int:
    """Rules are the '## ' headings in rules.md."""
    return len(re.findall(r"^## ", rules_text, flags=re.MULTILINE))


def get_api_key() -> str | None:
    """Read ANTHROPIC_API_KEY from .env (next to this file) or from the environment.

    .env is re-read on every call, so the user can paste the key in and click Check
    without restarting the app.
    """
    env_path = ROOT / ".env"
    values = dotenv_values(env_path) if env_path.exists() else {}
    key = (values.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    return key or None


# --------------------------------------------------------------------------- prompt / schema

SYSTEM_PROMPT = """You are exp-check, a rigorous but constructive reviewer of wet-lab experimental \
design in molecular and cell biology. A scientist pastes a protocol, a Methods paragraph, or a \
figure legend. You review it against the fixed checklist of rules given below (the RULES section) \
and report what a careful peer reviewer would flag.

How to work:

1. Identify what kind of text this is and which experiments it describes (for example: siRNA \
knockdown followed by western blot; CRISPR knockout clones assayed for proliferation).
2. Go through every rule in the RULES section. For each rule decide whether it is not applicable \
to this text, satisfied, or a problem.
3. Report only problems you can tie to the text. Quote the words that support each finding. If \
something is simply not mentioned, say "not stated in the provided text" rather than asserting \
the authors did not do it, and lower the severity when the text type would not normally contain \
that detail (a figure legend rarely lists catalogue numbers; a protocol rarely lists p-values).
4. Severity levels are critical, major and minor, as defined in the RULES section. Start from \
the rule's default severity and adjust only when the context clearly justifies it.
5. Suggestions must be concrete and actionable for a bench scientist: which control to add, \
which test to use, what sentence to add to the legend.
6. Do not invent rules beyond the list. Do not pad the report. If the text is good, say so.
7. Each rule begins with a '## ' heading; the first token after '## ' (for example R07) is the \
rule ID to use in rule_id. Use the rule's name as the title.
8. Write clear English for an international scientific audience.

Return the report as JSON that follows the provided schema.
"""

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "text_type": {
            "type": "string",
            "description": "One of: protocol, methods, figure_legend, other.",
        },
        "experiments_detected": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short names of the experiments the text describes.",
        },
        "overall_assessment": {
            "type": "string",
            "description": "Two to four sentences: the biggest risks and the overall verdict.",
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "title": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "description": "critical, major or minor.",
                    },
                    "issue": {
                        "type": "string",
                        "description": "What is missing or wrong, specific to this text.",
                    },
                    "why_reviewers_care": {"type": "string"},
                    "suggestion": {
                        "type": "string",
                        "description": "Concrete fix: what to add, change, or write.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Short quote from the text this finding is based on, or empty.",
                    },
                },
                "required": [
                    "rule_id",
                    "title",
                    "severity",
                    "issue",
                    "why_reviewers_care",
                    "suggestion",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "satisfied": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "note": {
                        "type": "string",
                        "description": "One sentence on how the text satisfies the rule.",
                    },
                },
                "required": ["rule_id", "note"],
                "additionalProperties": False,
            },
        },
        "not_applicable": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Rule IDs that do not apply to this text.",
        },
    },
    "required": [
        "text_type",
        "experiments_detected",
        "overall_assessment",
        "findings",
        "satisfied",
        "not_applicable",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- prompt assembly

RULE_ID_RE = re.compile(r"\bR0?(\d{1,2})\b")   # accepts "R07" and "R7"


def build_system(rules_text: str) -> list[dict]:
    """The system prompt sent with every check: fixed instructions + the current rules."""
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT + "\n\n# RULES\n\n" + rules_text,
            # The instructions + rules are identical for every check, so let the API cache them.
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_user_message(text: str, text_type_hint: str = "Auto-detect") -> str:
    return (
        f"Text type (as stated by the user): {text_type_hint}\n\n"
        "Text to check:\n<text>\n" + text.strip() + "\n</text>"
    )


def triggered_rule_ids(report: dict) -> list[str]:
    """Sorted list of rule IDs (e.g. ['R02', 'R07']) that the report's findings refer to."""
    ids = set()
    for f in report.get("findings", []) or []:
        m = RULE_ID_RE.search(str(f.get("rule_id", ""))) or RULE_ID_RE.search(str(f.get("title", "")))
        if m:
            ids.add(f"R{int(m.group(1)):02d}")
    return sorted(ids)


# --------------------------------------------------------------------------- API call


def run_check(text: str, text_type_hint: str, cfg: dict, rules_text: str, api_key: str) -> dict:
    """Send the text and rules to the model and return the parsed report as a dict."""
    client = anthropic.Anthropic(api_key=api_key)
    system = build_system(rules_text)
    user_message = build_user_message(text, text_type_hint)

    try:
        response = client.beta.messages.create(
            model=cfg["model"],
            max_tokens=int(cfg["max_tokens"]),
            # If the model's safety classifier declines a benign request (it can happen with
            # biology text), the API re-runs it on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": cfg["effort"],
                "format": {"type": "json_schema", "schema": REPORT_SCHEMA},
            },
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.AuthenticationError:
        raise CheckError(
            "The API key was rejected. Open .env, check that the key after ANTHROPIC_API_KEY= "
            "is complete (it starts with sk-ant-), save, and try again."
        )
    except anthropic.PermissionDeniedError:
        raise CheckError("This API key is not allowed to use the requested model.")
    except anthropic.NotFoundError:
        raise CheckError(
            f"Model '{cfg['model']}' was not found. Check the 'model' line in config.toml."
        )
    except anthropic.RateLimitError:
        raise CheckError("Rate limit reached. Wait a minute and try again.")
    except anthropic.BadRequestError as e:
        raise CheckError(f"The API rejected the request: {e.message}")
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise CheckError(f"Anthropic server error ({e.status_code}). Try again shortly.")
        raise CheckError(f"API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise CheckError("Could not reach the Anthropic API. Check your internet connection.")

    if response.stop_reason == "refusal":
        explanation = ""
        details = getattr(response, "stop_details", None)
        if details is not None and getattr(details, "explanation", None):
            explanation = f" ({details.explanation})"
        raise CheckError(
            "The model declined to review this text" + explanation + ". "
            "Try rephrasing or shortening the text."
        )
    if response.stop_reason == "max_tokens":
        raise CheckError(
            "The report was cut off because it exceeded max_tokens. "
            "Raise max_tokens in config.toml or check a shorter text."
        )

    raw = next((b.text for b in response.content if b.type == "text"), "")
    if not raw:
        raise CheckError("The model returned an empty response. Please try again.")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        raise CheckError("The model's answer could not be parsed as a report. Please try again.")

    report = _normalise(report)
    usage = response.usage
    report["_meta"] = {
        "model": response.model,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "cached_input_tokens": getattr(usage, "cache_read_input_tokens", None),
    }
    return report


def _normalise(report: dict) -> dict:
    """Make sure every finding has a known severity and the lists exist."""
    findings = []
    for f in report.get("findings", []) or []:
        sev = str(f.get("severity", "")).strip().lower()
        f["severity"] = sev if sev in SEVERITIES else "major"
        findings.append(f)
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    report["findings"] = findings
    report.setdefault("satisfied", [])
    report.setdefault("not_applicable", [])
    report.setdefault("experiments_detected", [])
    # Plain list of triggered rule IDs, so results can be compared by ID (used by the evaluation).
    report["triggered_rules"] = triggered_rule_ids(report)
    return report


# --------------------------------------------------------------------------- export


def report_to_markdown(report: dict, original_text: str) -> str:
    """Plain-text version of the report for downloading or pasting into notes."""
    counts = {s: sum(1 for f in report["findings"] if f["severity"] == s) for s in SEVERITIES}
    lines = [
        "# exp-check report",
        "",
        f"Text type: {report.get('text_type', '')}",
        "Experiments detected: " + (", ".join(report.get("experiments_detected", [])) or "-"),
        "",
        "## Overall assessment",
        "",
        report.get("overall_assessment", ""),
        "",
        f"## Findings ({counts['critical']} critical, {counts['major']} major, {counts['minor']} minor)",
        "",
    ]
    if not report["findings"]:
        lines.append("No problems found against the current rules.")
    for f in report["findings"]:
        lines += [
            f"### [{f['severity'].upper()}] {f['rule_id']} - {f['title']}",
            "",
            f"**Issue:** {f['issue']}",
            "",
            f"**Why reviewers care:** {f['why_reviewers_care']}",
            "",
            f"**Suggested fix:** {f['suggestion']}",
            "",
        ]
        if f.get("evidence"):
            lines += [f"> {f['evidence']}", ""]
    if report["satisfied"]:
        lines += ["## Rules satisfied", ""]
        lines += [f"- {s['rule_id']}: {s['note']}" for s in report["satisfied"]]
        lines.append("")
    if report["not_applicable"]:
        lines += ["## Not applicable", "", ", ".join(report["not_applicable"]), ""]
    if report.get("triggered_rules"):
        lines += ["Rules triggered: " + ", ".join(report["triggered_rules"]), ""]
    meta = report.get("_meta", {})
    if meta:
        lines += [f"_Checked with {meta.get('model', '')}_", ""]
    lines += ["## Text that was checked", "", "```", original_text.strip(), "```", ""]
    return "\n".join(lines)
