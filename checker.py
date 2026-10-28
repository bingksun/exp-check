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

# Bump this when the prompt or schema changes; the evaluation records it with every run.
PROMPT_VERSION = "v3"

SYSTEM_PROMPT = """You are exp-check, a rigorous but fair reviewer of wet-lab experimental design in \
molecular and cell biology. A scientist pastes a protocol, a Methods paragraph, or a figure legend. \
You review it against the fixed checklist of rules given below (the RULES section) and report what a \
careful, reasonable peer reviewer would flag.

How to work:

1. Identify the kind of text (protocol, methods, figure legend) and the experiments it describes \
(for example: siRNA knockdown followed by western blot; CRISPR knockout clones assayed for \
proliferation).

2. Place every rule in exactly one of three places: findings (violated), satisfied (one sentence \
naming the words that satisfy it), or not_applicable (the text contains no experiment of that kind). \
A clean text has an empty findings list and a full satisfied list, and its overall assessment says \
that no problems were found against the rules.

3. A finding requires a clear violation, of one of two kinds.
(a) The text states a practice that a rule calls wrong or insufficient: an unmatched or \
time-mismatched control; untransfected, untransduced or parental Cas9-free cells as the only \
comparator; statistics computed on wells, lanes, fields or technical replicates, or on n < 3; \
pairwise t-tests across three or more groups; a rescue construct that is not resistant to the \
reagent; a reference gene the treatment is known to alter; depth normalisation for a claimed \
global change; "efficiently depleted" with no number; asterisks or "significant" with no p-value \
or threshold; a "representative" image with no quantification; a p-value above 0.05 described as \
a trend; a fold change or IC50 reported with neither n nor variability. A stated insufficient \
practice is a finding whatever the text type.
(b) The text describes an experiment and states a result or conclusion, but is silent on a design \
element the rule requires and a reader needs in order to trust that result: which negative \
control was used; a non-targeting RNAi control, or a Cas9-expressing non-targeting control for \
CRISPR; a second siRNA, shRNA or guide; protein-level validation of the knockdown or knockout; an \
off-target statement for CRISPR; a rescue, or a reason for omitting one, whenever a phenotype of \
the knockdown or knockout cells is reported; a comparator for every manipulated variable (a \
vehicle arm for a compound as well as a non-targeting arm for a gene); n and what it counts; the statistical test when a difference is claimed; a loading \
control when a blot is quantified; a reference gene when qPCR is the readout; randomisation and \
blinding for animal work or for scoring by eye. Design elements are never assumed to be elsewhere \
in the paper, whatever the text type. Write "not stated in the text" in the issue and quote the \
sentence that makes the element necessary (the comparison or the conclusion).

4. Silence about anything else is not a finding in any text type: catalogue numbers, RRIDs, clones, \
dilutions, suppliers, cell-line provenance, authentication, mycoplasma status, passage range, \
primer sequences, kits, instruments, the expression level of a rescue construct, which clone was \
rescued, whether a named control was "handled identically", the time point of validation versus \
readout, or what the error bars show when no figure or error bars are described. Assume these are \
reported elsewhere and mention them in notes at most. A pointer such as "sequences in Table S1" or \
"rescue in Fig. S4" counts as provided. The questions under "Check:" in a rule describe a complete \
description; a "no" to one of them is not by itself a violation.

5. Judge silence by text type. A figure legend normally carries n, what the error bars show, the \
test, p-values and the identity of what it shows, but not protocol steps. A protocol that stops at \
the bench steps carries reagents, controls and the replicate structure and is not faulted for \
leaving out results; a protocol that includes an analysis step is judged on that step like a \
Methods text. A short Methods excerpt may defer reporting details to legends or supplementary \
material, never the design.

6. A rule is satisfied when what the text states meets the rule, not merely when the text mentions \
the topic. Once the text meets what the rule mainly asks for, do not add a finding because you \
would have wanted more detail. A named control that is the wrong control, an n that counts the \
wrong thing, or a named test that does not fit the design is a violation, not a request for detail.

7. Severity (critical, major, minor) follows the rule's default and reflects the impact on the \
conclusion. "Minor" is for real but low-impact violations; it is not a place for remarks that are \
not violations. Such remarks, if any, go in the notes field in one or two sentences.

8. Report only problems you can tie to the text. "Unsure" means the text is ambiguous about what \
was done; it does not mean the text is silent. Do not build a design the text does not state: do \
not report a statistics rule because the number of groups is unknown, because the post-hoc test of \
a named ANOVA is not spelled out, or because a comparison "does not cover" an arm the text does \
not analyse.

9. Suggestions must be concrete and actionable for a bench scientist: which control to add, which \
test to use, what sentence to add to the legend.

10. Each rule begins with a '## ' heading; the first token after '## ' (for example R07) is the \
rule ID to use in rule_id. Use the rule's name as the title. Where a rule carries "Satisfied when" \
or "Not a finding" lines, follow them. Write clear English for an international scientific \
audience.

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
            "description": "Two to four sentences: the verdict first, then the biggest risks if there are any.",
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
        "notes": {
            "type": "string",
            "description": "Optional remarks that are not rule violations (one or two sentences), "
                           "or an empty string.",
        },
    },
    "required": [
        "text_type",
        "experiments_detected",
        "overall_assessment",
        "findings",
        "satisfied",
        "not_applicable",
        "notes",
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
    report["notes"] = str(report.get("notes") or "").strip()
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
    if report.get("notes"):
        lines += ["## Notes", "", report["notes"], ""]
    if report.get("triggered_rules"):
        lines += ["Rules triggered: " + ", ".join(report["triggered_rules"]), ""]
    meta = report.get("_meta", {})
    if meta:
        lines += [f"_Checked with {meta.get('model', '')}_", ""]
    lines += ["## Text that was checked", "", "```", original_text.strip(), "```", ""]
    return "\n".join(lines)
