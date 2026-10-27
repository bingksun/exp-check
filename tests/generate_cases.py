"""Generate synthetic evaluation cases with Claude Opus 5.5 and write them to tests/cases/syn_*.md.

    python tests/generate_cases.py              # all categories (asks for confirmation first)
    python tests/generate_cases.py --category rnai --yes
    python tests/generate_cases.py --dry-run    # print the prompts, call nothing

Each category is one API call that returns N flawed cases followed by M clean cases. The
answer key (planted rules) comes from the generator; review it before trusting the scores.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import evalkit as ek
from evalkit import checker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GEN_MODEL = "claude-opus-5-5"
LOG_FILE = ek.RESULTS_DIR / "generation_log.jsonl"

# key, label, description, flawed cases, clean cases, rules to plant from
PLAN = [
    ("rnai", "RNAi",
     "RNAi loss-of-function experiments (siRNA, shRNA, dsRNA feeding, miRNA mimics) in cell lines or model organisms",
     7, 2, "R01 R02 R03 R04 R06 R07 R08 R11 R12"),
    ("crispr", "CRISPR",
     "CRISPR experiments (Cas9 knockout clones or pools, CRISPRi/CRISPRa, base editing) and the phenotypes measured",
     7, 2, "R01 R02 R03 R04 R08 R09 R10 R11 R12"),
    ("cuttag", "CUT&Tag",
     "chromatin profiling by CUT&Tag, CUT&RUN or ChIP-seq, including antibody validation, replicates, controls, "
     "normalization and peak calling",
     6, 1, "R01 R02 R03 R04 R08 R12"),
    ("qpcr", "qPCR",
     "RT-qPCR gene-expression experiments (RNA preparation, reference genes, replicates, ddCt, statistics)",
     7, 2, "R01 R02 R03 R04 R08 R12"),
    ("western", "Western",
     "Western blot / immunoblot experiments and their quantification (antibodies, loading controls, replicates, statistics)",
     7, 1, "R01 R02 R03 R04 R08 R12"),
    ("animal", "Animal",
     "in vivo experiments in mice or rats (drug treatment, xenografts, behaviour, histology scoring)",
     6, 2, "R01 R02 R03 R04 R05 R12"),
]

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text_type": {"type": "string", "description": "methods, figure_legend or protocol"},
                    "text": {"type": "string"},
                    "planted_rules": {"type": "array", "items": {"type": "string"},
                                      "description": "rule IDs such as R07; empty for a clean case"},
                    "rationale": {"type": "string",
                                  "description": "one sentence per planted rule: how the text violates it"},
                    "how_other_rules_are_satisfied": {"type": "string"},
                },
                "required": ["text_type", "text", "planted_rules", "rationale", "how_other_rules_are_satisfied"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cases"],
    "additionalProperties": False,
}

GEN_SYSTEM = """You write test cases for exp-check, a tool that reviews wet-lab experimental-design text against \
a fixed list of rules (given below). A test case is a short, realistic piece of manuscript text in English \
(a Methods paragraph, a figure legend, or a protocol excerpt) plus an answer key.

Two kinds of cases:
- FLAWED: the text deliberately violates 1 to 3 of the rules (the "planted" rules). Every other rule that \
applies to the experiment must be clearly satisfied in the text (name the matched control, state n as \
independent biological replicates of at least three, name the statistical test and what error bars show, give \
reagent identifiers, and so on) or be clearly not applicable. A careful reader applying the rules should find \
exactly the planted problems and nothing else.
- CLEAN: the text satisfies every applicable rule explicitly. Nothing should be flagged.

Requirements:
- 60 to 180 words per text, realistic manuscript style. Never hint at or explain the flaw inside the text.
- Use placeholder names such as GENE-A, GENE-B, protein P, compound Z; realistic reagent identifiers such as \
"Abcam ab12345, RRID:AB_123456" or "Dharmacon D-001810-01"; varied cell lines and organisms.
- Vary the text type (methods / figure_legend / protocol) and the planted rules across cases. A planted problem \
must be an unambiguous violation of the rule as written, not a matter of taste.
- Make each case distinct; do not reuse the same experiment with small edits.
- For each case give: text_type, text, planted_rules (rule IDs like "R07"; an empty list for a clean case), \
rationale (one sentence per planted rule explaining how the text violates it), and \
how_other_rules_are_satisfied (one or two sentences).

The rules:

"""


def category_prompt(desc: str, n_flawed: int, n_clean: int, relevant: str) -> str:
    return (
        f"Category: {desc}.\n\n"
        f"Write {n_flawed} FLAWED cases followed by {n_clean} CLEAN cases, in that order "
        f"({n_flawed + n_clean} cases in total).\n"
        f"Choose planted rules from: {relevant}. Across the flawed cases, plant each of these rules at least "
        "once, and give no two cases the same set of planted rules."
    )


def validate(cases_out: list, n_flawed: int, n_clean: int) -> list:
    errs = []
    if len(cases_out) != n_flawed + n_clean:
        errs.append(f"expected {n_flawed + n_clean} cases, got {len(cases_out)}")
    for i, c in enumerate(cases_out):
        rules = set(c.get("planted_rules") or [])
        bad = rules - set(ek.ALL_RULES)
        if bad:
            errs.append(f"case {i + 1}: unknown rule ids {sorted(bad)}")
        words = len(str(c.get("text", "")).split())
        if not 40 <= words <= 230:
            errs.append(f"case {i + 1}: {words} words (expected 60-180)")
        if i < n_flawed and not rules:
            errs.append(f"case {i + 1}: flawed case has no planted rules")
        if i >= n_flawed and rules:
            errs.append(f"case {i + 1}: clean case has planted rules {sorted(rules)}")
        if c.get("text_type") not in ("methods", "figure_legend", "protocol"):
            errs.append(f"case {i + 1}: text_type {c.get('text_type')!r}")
        if re.search(r"^## ", str(c.get("text", "")), re.M):
            errs.append(f"case {i + 1}: text contains a '## ' heading line (would break the case-file format)")
    return errs


def generate_category(client, key, label, desc, n_flawed, n_clean, relevant, rules_text, dry_run=False):
    system = [{"type": "text", "text": GEN_SYSTEM + rules_text, "cache_control": {"type": "ephemeral"}}]
    user = category_prompt(desc, n_flawed, n_clean, relevant)
    if dry_run:
        print(f"--- {label} ---\n{user}\n")
        return None
    with client.beta.messages.stream(
        model=GEN_MODEL,
        max_tokens=64000,   # thinking counts toward this; 9 cases at effort "high" exceeded 32000 once
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": GEN_SCHEMA}},
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    usage = ek.usage_from_message(msg)
    cost = ek.usage_cost(usage, ek.MODELS["opus55"]["price"], batch=False)
    ek.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "category": key,
                            "model": msg.model, "stop_reason": msg.stop_reason, "usage": usage,
                            "cost_usd": round(cost, 4)}) + "\n")
    if msg.stop_reason == "refusal":
        print(f"  {label}: 模型拒绝了这次请求，没有生成。")
        return None
    if msg.stop_reason == "max_tokens":
        print(f"  {label}: 输出在 max_tokens 处被截断，没有写入。把 generate_cases.py 里的 max_tokens 调大再试。")
        return None
    served = msg.model or GEN_MODEL
    if served != GEN_MODEL:
        print(f"  {label}: 注意，{GEN_MODEL} 拒绝了请求，实际由 {served} 生成。")
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print(f"  {label}: 返回的不是合法 JSON，没有写入。")
        return None
    cases_out = data.get("cases", [])
    errs = validate(cases_out, n_flawed, n_clean)
    if errs:
        print(f"  {label}: 生成结果不合格，没有写入：")
        for e in errs:
            print("    - " + e)
        return None
    print(f"  {label}: {len(cases_out)} 个案例，{usage['output_tokens']} 输出 token，约 ${cost:.2f}")
    return cases_out, served


def write_cases(key, label, cases_out, n_flawed, served_model=GEN_MODEL):
    today = datetime.now(timezone.utc).date().isoformat()
    for i, c in enumerate(cases_out, start=1):
        rules = set(c["planted_rules"])
        title = f"{c['text_type']}; " + (f"planted {', '.join(sorted(rules))}" if rules else "clean case")
        notes = [
            f"Rationale (generator): {c['rationale'].strip()}",
            f"How other rules are satisfied (generator): {c['how_other_rules_are_satisfied'].strip()}",
            f"Generated by {served_model} on {today}. Answer key reviewed by a human: no.",
        ]
        ek.write_case_file(
            ek.CASES_DIR / f"syn_{key}_{i:02d}.md",
            id=f"syn_{key}_{i:02d}", source="synthetic", category=label, title=title,
            answer=rules, tolerated=set(), text=c["text"], notes=notes,
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--category", nargs="*", help="subset of: " + " ".join(p[0] for p in PLAN))
    ap.add_argument("--dry-run", action="store_true", help="print the prompts and call nothing")
    ap.add_argument("--force", action="store_true", help="overwrite existing syn_* files for the category")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    plan = [p for p in PLAN if not args.category or p[0] in args.category]
    if not plan:
        print("--category 只能从这些里选：" + " ".join(p[0] for p in PLAN))
        sys.exit(1)
    cfg = checker.load_config()
    rules_text = checker.load_rules(cfg)

    if args.dry_run:
        for key, label, desc, nf, nc, rel in plan:
            generate_category(None, key, label, desc, nf, nc, rel, rules_text, dry_run=True)
        return

    key = checker.get_api_key()
    if not key:
        print("没有找到 API key：请在项目文件夹的 .env 里填好 ANTHROPIC_API_KEY 再运行。")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=key)

    if args.force and (ek.RESULTS_DIR / "batches.json").exists():
        print("已经提交过评测（tests/results/batches.json 存在）。重新生成会让旧结果和新答案对不上，"
              "请先把该文件改名或删除，再加 --force。")
        sys.exit(1)

    todo = []
    for p in plan:
        existing = sorted(ek.CASES_DIR.glob(f"syn_{p[0]}_*.md"))
        if existing and not args.force:
            print(f"  {p[1]}: 已有 {len(existing)} 个文件，跳过（要重新生成请加 --force）")
            continue
        todo.append(p)
    if not todo:
        return
    n_total = sum(p[3] + p[4] for p in todo)
    print(f"将用 {GEN_MODEL} 生成 {n_total} 个案例（{len(todo)} 次调用，标准价，每次约 $0.2-0.4）。")
    if not args.yes:
        try:
            ans = input("确认开始？输入 YES 回车继续，其他任何输入取消：")
        except EOFError:
            ans = ""
        if ans.strip() != "YES":
            print("已取消。")
            sys.exit(1)

    for key_, label, desc, nf, nc, rel in todo:
        out = generate_category(client, key_, label, desc, nf, nc, rel, rules_text)
        if out:
            cases_out, served = out
            write_cases(key_, label, cases_out, nf, served)
    cases = ek.load_cases()
    syn = [c for c in cases if c.source == "synthetic"]
    print(f"现在 tests/cases/ 共 {len(cases)} 个案例，其中合成 {len(syn)} 个（干净 {sum(c.clean for c in syn)} 个）。")


if __name__ == "__main__":
    main()
