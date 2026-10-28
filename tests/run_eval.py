"""exp-check evaluation runner.

    python tests/run_eval.py estimate [--latency-n 5]   # count tokens and print the cost estimate (free)
    python tests/run_eval.py submit   [--yes]           # create one batch per model (asks for confirmation)
    python tests/run_eval.py status                     # show batch progress
    python tests/run_eval.py collect                    # download finished batches, score, write the reports
    python tests/run_eval.py score                      # re-score from the downloaded raw files
    python tests/run_eval.py latency --n 5 [--yes]      # direct (non-batch) calls on a few cases to time them
    python tests/run_eval.py compare --tag prompt-v2    # before/after table: baseline results vs a tagged run

Add --tag NAME to submit/status/collect/score/latency to keep a separate run (for example after a
prompt change) in tests/results/NAME/ with its own docs/eval-NAME.md, without touching the baseline
results or the README table.

Console output is in Chinese for the project owner; the files written to the repo are in English.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

import evalkit as ek
from evalkit import checker

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Rough output size per check (thinking tokens count as output). Used only for the estimate.
OUTPUT_TOKENS_GUESS = {"haiku55": 3000, "sonnet55": 3500, "opus55": 4000, "fable51": 4500}


class Paths:
    """Where one evaluation run keeps its files. The baseline run has no tag."""

    def __init__(self, tag: str | None = None):
        if tag and not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
            die("--tag 只能用字母、数字、点、横线和下划线。")
        self.tag = tag
        self.results_dir = ek.RESULTS_DIR / tag if tag else ek.RESULTS_DIR
        self.batches_file = self.results_dir / "batches.json"
        self.latency_file = self.results_dir / "latency.jsonl"
        self.summary_file = self.results_dir / "summary.json"
        self.eval_md = ek.ROOT / "docs" / (f"eval-{tag}.md" if tag else "eval.md")

    def raw_path(self, mk: str) -> Path:
        return self.results_dir / f"raw_{mk}.jsonl"


P = Paths()


def die(msg: str) -> None:
    print(msg)
    sys.exit(1)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_client() -> anthropic.Anthropic:
    key = checker.get_api_key()
    if not key:
        die("没有找到 API key：请在项目文件夹的 .env 里填好 ANTHROPIC_API_KEY 再运行。")
    return anthropic.Anthropic(api_key=key)


def load_setup():
    cfg = checker.load_config()
    rules = checker.load_rules(cfg)
    cases = ek.load_cases()
    if not cases:
        die("tests/cases/ 里没有案例文件。")
    return cfg, rules, cases


def model_keys(args) -> list:
    keys = [k for k in ek.MODELS if not args.models or k in args.models]
    if not keys:
        die(f"--models 只能从这些里选：{', '.join(ek.MODELS)}")
    return keys


def confirm(prompt: str, yes: bool) -> None:
    if yes:
        return
    try:
        ans = input(prompt + "  输入 YES 回车继续，其他任何输入取消：")
    except EOFError:
        ans = ""
    if ans.strip() != "YES":
        die("已取消，没有提交，没有花钱。")


def load_record() -> dict:
    if not P.batches_file.exists():
        die(f"还没有提交过 Batch（找不到 {P.batches_file}）。先运行 submit。")
    return json.loads(P.batches_file.read_text(encoding="utf-8"))


def save_record(rec: dict) -> None:
    P.results_dir.mkdir(parents=True, exist_ok=True)
    P.batches_file.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- estimate


def estimate_table(client, cfg, rules, cases, keys, reps):
    """Returns rows (label, n_requests, input_tokens, output_guess, cost_per_request, cost_total)."""
    step = max(1, len(cases) // 8)
    sample = cases[::step][:8]
    rows = []
    for mk in keys:
        m = ek.MODELS[mk]
        counts = []
        for c in sample:
            p = ek.build_params(m["id"], c, cfg, rules)
            try:
                # the JSON schema is part of the billed prompt, so count it too
                r = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                                 output_config={"format": p["output_config"]["format"]})
            except anthropic.BadRequestError:
                r = client.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"])
            counts.append(r.input_tokens)
        in_tok = sum(counts) / len(counts)
        out_tok = OUTPUT_TOKENS_GUESS[mk]
        per = ek.BATCH_DISCOUNT * (in_tok * m["price"]["input"] + out_tok * m["price"]["output"]) / 1e6
        n_req = len(cases) * reps
        rows.append((m["label"], n_req, in_tok, out_tok, per, per * n_req))
    return rows, len(sample)


def print_estimate(rows, n_sample, reps, n_cases):
    print(f"案例 {n_cases} 个 × 每模型 {reps} 遍 = 每模型 {n_cases * reps} 次请求。"
          f"输入 token 用 {n_sample} 个案例实测取平均；输出 token 是估计值（含模型思考）。")
    print()
    print(f"{'模型':<20}{'请求数':>8}{'输入tok/次':>12}{'输出tok/次(估)':>16}{'单次(Batch价)':>16}{'合计':>12}")
    total = 0.0
    for label, n_req, in_tok, out_tok, per, cost in rows:
        total += cost
        print(f"{label:<20}{n_req:>8}{in_tok:>12.0f}{out_tok:>16}{per:>16.4f}{cost:>12.2f}")
    print(f"{'Batch 合计':<20}{'':>8}{'':>12}{'':>16}{'':>16}{total:>12.2f}  美元")
    print(f"输出长度不确定，实际大约在 ${0.6 * total:.2f} 到 ${1.4 * total:.2f} 之间；"
          "系统提示词命中缓存时会再便宜一些。")
    return total


def cmd_estimate(args):
    client = get_client()
    cfg, rules, cases = load_setup()
    keys = model_keys(args)
    rows, n_sample = estimate_table(client, cfg, rules, cases, keys, args.reps)
    total = print_estimate(rows, n_sample, args.reps, len(cases))
    if args.latency_n:
        print()
        print(f"可选：直连测速，每个模型 {args.latency_n} 次，按标准价（Batch 价的两倍）：")
        lat_total = 0.0
        for (label, _, in_tok, out_tok, per, _), mk in zip(rows, keys):
            cost = args.latency_n * per / ek.BATCH_DISCOUNT
            lat_total += cost
            print(f"  {label:<20}${cost:.2f}")
        print(f"  测速合计 ≈ ${lat_total:.2f}；加上 Batch 共约 ${total + lat_total:.2f} 美元")


# --------------------------------------------------------------------------- submit


def cmd_submit(args):
    client = get_client()
    cfg, rules, cases = load_setup()
    keys = model_keys(args)
    case_ids = [c.id for c in cases]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Resumable: an existing record is continued (only the missing models are submitted)
    # unless --force, which archives the old record and starts over.
    rec = None
    if P.batches_file.exists():
        old = load_record()
        if args.force:
            archive = P.batches_file.with_name(f"batches.{stamp}.old.json")
            P.batches_file.rename(archive)
            print(f"旧的 Batch 记录已改名为 {archive.name}（不会再被取回），这次从头开始。")
        else:
            done = {b["model_key"]: b for b in old["batches"]}
            for mk in [k for k in keys if k in done]:
                print(f"  {ek.MODELS[mk]['label']}: 已提交过（batch {done[mk]['batch_id']}），跳过")
            keys = [k for k in keys if k not in done]
            if not keys:
                die("这些模型都已经提交过了。要全部重新提交请加 --force（旧记录会改名保存，不会丢）。")
            if old["case_ids"] != case_ids or old["reps"] != args.reps:
                die("案例集或重复次数和上次提交时不一样，不能把新模型追加到旧记录里。要重新开始请加 --force。")
            if old.get("prompt_version", "v1") != checker.PROMPT_VERSION:
                die(f"上次提交用的是提示词 {old.get('prompt_version', 'v1')}，现在是 {checker.PROMPT_VERSION}，"
                    "不能混在一个记录里。请用 --tag 开一个新的运行，或加 --force 重新开始。")
            rec = old
            print("继续上次的记录，只提交剩下的模型：" + ", ".join(ek.MODELS[k]["label"] for k in keys))

    rows, n_sample = estimate_table(client, cfg, rules, cases, keys, args.reps)
    print_estimate(rows, n_sample, args.reps, len(cases))
    if P.tag:
        print(f"（这是带标签的运行 {P.tag}，结果存在 {P.results_dir}，不会覆盖基线结果。）")
    print(f"提示词版本：{checker.PROMPT_VERSION}")
    print()
    confirm("确认提交 Batch 并按上表付费？", args.yes)

    if rec is None:
        rec = {
            "created_at": now(),
            "tag": P.tag,
            "prompt_version": checker.PROMPT_VERSION,
            "reps": args.reps,
            "effort": cfg["effort"],
            "max_tokens": int(cfg["max_tokens"]),
            "n_cases": len(cases),
            "case_ids": case_ids,
            "batches": [],
        }
    # Old outputs for the models being submitted would otherwise be scored as if they were new.
    for p in [P.raw_path(mk) for mk in keys] + [P.summary_file]:
        if p.exists():
            moved = p.with_name(f"{p.stem}.{stamp}.old{p.suffix}")
            p.rename(moved)
            print(f"  旧文件 {p.name} 已改名为 {moved.name}")

    for mk in keys:
        m = ek.MODELS[mk]
        requests = [
            Request(
                custom_id=ek.custom_id(mk, c.id, rep),
                params=MessageCreateParamsNonStreaming(**ek.build_params(m["id"], c, cfg, rules)),
            )
            for c in cases
            for rep in range(1, args.reps + 1)
        ]
        try:
            batch = client.messages.batches.create(requests=requests)
        except anthropic.APIError as e:
            print(f"  {m['label']}: 提交失败：{e}")
            print(f"已成功提交的模型都记在 {P.batches_file} 里，没有丢。问题解决后再运行一次 submit，只会提交剩下的模型。")
            sys.exit(1)
        rec["batches"].append({
            "model_key": mk,
            "model_id": m["id"],
            "batch_id": batch.id,
            "n_requests": len(requests),
            "status": batch.processing_status,
        })
        save_record(rec)
        print(f"  {m['label']}: 已提交 batch {batch.id}（{len(requests)} 次请求）")
    print()
    print(f"Batch 编号已保存到 {P.batches_file}。通常 1 小时内跑完（最长 24 小时），结果保留 29 天。")
    tag_opt = f" --tag {P.tag}" if P.tag else ""
    print(f"之后运行  python tests/run_eval.py collect{tag_opt}  取结果并生成报表"
          + ("。" if P.tag else "（或双击 collect_results.bat）。"))


# --------------------------------------------------------------------------- status / collect


def refresh_status(client, rec) -> list:
    """Print each batch's progress and return the ones that are not finished."""
    pending = []
    for b in rec["batches"]:
        bt = client.messages.batches.retrieve(b["batch_id"])
        rc = bt.request_counts
        b["status"] = bt.processing_status
        label = ek.MODELS[b["model_key"]]["label"]
        print(f"  {label:<20}{bt.processing_status:<12}处理中 {rc.processing:>4}  成功 {rc.succeeded:>4}  "
              f"出错 {rc.errored:>3}  取消 {rc.canceled:>3}  过期 {rc.expired:>3}")
        if bt.processing_status != "ended":
            pending.append(b)
    save_record(rec)
    return pending


def cmd_status(args):
    client = get_client()
    rec = load_record()
    pending = refresh_status(client, rec)
    print("全部完成。" if not pending else f"还有 {len(pending)} 个没跑完。")


def download(client, b) -> int:
    path = P.raw_path(b["model_key"])
    lines = []
    for res in client.messages.batches.results(b["batch_id"]):
        rt = res.result.type
        if rt == "succeeded":
            rec = ek.raw_from_message(res.custom_id, res.result.message)
        else:
            e = getattr(res.result, "error", None)
            inner = getattr(e, "error", None)
            etype = getattr(inner, "type", None) or getattr(e, "type", None) or rt
            emsg = getattr(inner, "message", None) or getattr(e, "message", None) or ""
            rec = {"custom_id": res.custom_id, "result_type": rt, "error": f"{etype}: {emsg}".strip(": "),
                   "usage": {}, "text": ""}
        lines.append(json.dumps(rec, ensure_ascii=False))
    P.results_dir.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def cmd_collect(args):
    client = get_client()
    rec = load_record()
    print("Batch 状态：")
    pending = refresh_status(client, rec)
    for b in rec["batches"]:
        if b["status"] != "ended":
            continue
        if P.raw_path(b["model_key"]).exists() and not args.redownload:
            print(f"  {ek.MODELS[b['model_key']]['label']}: 结果文件已存在，跳过下载（要重新下载请加 --redownload）")
            continue
        n = download(client, b)
        print(f"  {ek.MODELS[b['model_key']]['label']}: 已下载 {n} 条结果 → {P.raw_path(b['model_key']).name}")
    if pending:
        print(f"还有 {len(pending)} 个 Batch 没跑完，稍后再运行一次"
              + ("。" if P.tag else "（双击 collect_results.bat 即可）。"))
    have = [b for b in rec["batches"] if P.raw_path(b["model_key"]).exists()]
    if not have:
        return
    do_score(rec, partial=bool(pending))


def load_runs(mk: str) -> list:
    runs = []
    for line in P.raw_path(mk).read_text(encoding="utf-8").splitlines():
        if line.strip():
            runs.append(ek.run_from_raw(json.loads(line)))
    return runs


def load_latency() -> dict:
    out = {}
    if not P.latency_file.exists():
        return out
    for line in P.latency_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            run = ek.run_from_raw(json.loads(line))
            out.setdefault(run.model_key, []).append(run)
    return out


def do_score(rec: dict, partial: bool = False) -> None:
    cases = ek.load_cases()
    submitted = set(rec["case_ids"])
    cases_used = [c for c in cases if c.id in submitted]
    missing = submitted - {c.id for c in cases}
    if missing:
        die(f"这些案例当时提交了，现在在 tests/cases/ 里找不到（被删或改名？）：{sorted(missing)}")
    runs_by_model = {}
    case_ids = {c.id for c in cases_used}
    for b in rec["batches"]:
        if not P.raw_path(b["model_key"]).exists():
            continue
        runs = load_runs(b["model_key"])
        stray = sorted({r.case_id for r in runs if r.case_id not in case_ids})
        if stray:
            print(f"  警告：{ek.MODELS[b['model_key']]['label']} 的结果文件里有 {len(stray)} 个不属于本次案例集的案例，"
                  f"已忽略（例如 {', '.join(stray[:3])}）。")
            runs = [r for r in runs if r.case_id in case_ids]
        runs_by_model[b["model_key"]] = runs
    if not runs_by_model:
        die("没有可打分的结果文件（raw_*.jsonl）。先运行 collect。")
    summary = ek.score_all(runs_by_model, cases_used, load_latency())
    summary["partial"] = partial
    summary["reps"] = rec["reps"]
    summary["tag"] = P.tag
    summary["prompt_version"] = rec.get("prompt_version", "v1")
    P.results_dir.mkdir(parents=True, exist_ok=True)
    P.summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    ek.write_eval_md(summary, rec["reps"], {"effort": rec["effort"], "max_tokens": rec["max_tokens"]}, P.eval_md)
    readme_done = False if (partial or P.tag) else ek.update_readme(summary)

    print()
    print(f"{'模型':<20}{'召回率':>8}{'误报率(全部)':>12}{'误报率(严重/主要)':>16}{'干净案例被冤枉':>16}"
          f"{'拒答':>8}{'平均费用/次':>12}{'成功/总数':>12}")
    for e in summary["models"].values():
        m = e["all"]
        print(f"{e['label']:<20}{ek.pct(m['recall']):>8}{ek.pct(m['fp_rate']):>12}{ek.pct(m.get('fp_rate_major')):>16}"
              f"{ek.pct(m['clean_flagged_major']):>16}{ek.pct(m.get('refusal_rate')):>8}"
              f"{ek.money(m['mean_cost_usd']):>12}{str(m['ok']) + '/' + str(m['runs']):>12}")
    print()
    print(f"详细报表已写入 {P.eval_md}（{'部分结果' if partial else '全部结果'}）。")
    if readme_done:
        print("README.md 里的精简表已更新。")
    elif P.tag:
        print("带标签的运行不改 README；运行 compare 可以生成前后对比表。")
    elif not partial:
        print("README.md 里没有找到 <!-- eval-table-start --> 标记，精简表没有更新。")


def cmd_score(args):
    rec = load_record()
    do_score(rec, partial=any(b.get("status") != "ended" for b in rec["batches"]))


# --------------------------------------------------------------------------- latency


def cmd_latency(args):
    client = get_client()
    cfg, rules, cases = load_setup()
    keys = model_keys(args)
    sample = [c for c in cases if c.source == "handwritten" and not c.clean][: args.n] or cases[: args.n]
    est = 0.0
    for mk in keys:
        m = ek.MODELS[mk]
        est += args.n * (4000 * m["price"]["input"] + OUTPUT_TOKENS_GUESS[mk] * m["price"]["output"]) / 1e6
    print(f"直连测速：{len(keys)} 个模型 × {len(sample)} 个案例，标准价，预计约 ${est:.2f}。")
    confirm("确认开始？", args.yes)
    P.results_dir.mkdir(parents=True, exist_ok=True)
    with P.latency_file.open("a", encoding="utf-8") as f:
        for mk in keys:
            m = ek.MODELS[mk]
            for c in sample:
                cid = ek.custom_id(mk, c.id, 0)
                p = ek.build_params(m["id"], c, cfg, rules)
                t0 = time.perf_counter()
                try:
                    msg = client.messages.create(**p)
                    dt = time.perf_counter() - t0
                    rec = ek.raw_from_message(cid, msg, dt)
                    print(f"  {m['label']:<20}{c.id:<10}{dt:6.1f} s  stop={msg.stop_reason}")
                except anthropic.APIError as e:
                    rec = {"custom_id": cid, "result_type": "errored", "error": str(e), "usage": {},
                           "text": "", "latency_s": None}
                    print(f"  {m['label']:<20}{c.id:<10} 出错：{e}")
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
    print(f"耗时记录已追加到 {P.latency_file}。")
    if P.batches_file.exists():
        rec = load_record()
        if any(P.raw_path(b["model_key"]).exists() for b in rec["batches"]):
            do_score(rec, partial=any(b["status"] != "ended" for b in rec["batches"]))


# --------------------------------------------------------------------------- compare


COMPARE_ROWS = [
    ("Recall", "recall", ek.pct),
    ("Precision", "precision", ek.pct),
    ("FP rate (all)", "fp_rate", ek.pct),
    ("FP rate (critical/major)", "fp_rate_major", ek.pct),
    ("FP per run (all)", "fp_per_run", ek.num),
    ("FP per run (critical/major)", "fp_per_run_major", ek.num),
    ("Clean cases flagged (critical/major)", "clean_flagged_major", ek.pct),
    ("Clean cases flagged (any)", "clean_flagged_any", ek.pct),
    ("Consistency", "consistency", ek.pct),
    ("Refused", "refusal_rate", ek.pct),
    ("Mean cost / check (batch)", "mean_cost_usd", ek.money),
]


def run_label(summary: dict) -> str:
    return f"prompt {summary.get('prompt_version', 'v1')}" + (f" ({summary['tag']})" if summary.get("tag") else "")


def compare_markdown(runs: list, keys: list) -> list:
    """runs: [baseline summary, tagged summary, ...] - one column per run."""
    labels = [run_label(s) for s in runs]
    lines = []
    for mk in keys:
        entries = [s["models"][mk] for s in runs]
        lines += [f"### {entries[0]['label']}: " + " vs ".join(labels), "",
                  "| Metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(runs)]
        for label, key, fmt in COMPARE_ROWS:
            lines.append(f"| {label} | " + " | ".join(fmt(e["all"].get(key)) for e in entries) + " |")
        lines.append("| Runs ok / total | " + " | ".join(f"{e['all']['ok']} / {e['all']['runs']}" for e in entries) + " |")
        lines += ["", "| Subset / metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(runs)]
        for src in ("handwritten", "synthetic"):
            for label, key, fmt in (("recall", "recall", ek.pct), ("FP rate (critical/major)", "fp_rate_major", ek.pct),
                                    ("clean cases flagged (critical/major)", "clean_flagged_major", ek.pct)):
                cells = " | ".join(fmt((e.get(src) or {}).get(key)) for e in entries)
                lines.append(f"| {src} / {label} | {cells} |")
        lines.append("")
    return lines


def replace_block(text: str, start: str, end: str, block: str, append_if_missing: bool) -> str | None:
    if start in text and end in text:
        pre, rest = text.split(start, 1)
        _, post = rest.split(end, 1)
        return pre + start + "\n" + block + "\n" + end + post
    if append_if_missing:
        return text.rstrip("\n") + "\n\n" + start + "\n" + block + "\n" + end + "\n"
    return None


def cmd_compare(args):
    tags = args.tags or ([args.tag] if args.tag else [])
    if not tags:
        die("compare 需要 --tag 或 --tags，例如：python tests/run_eval.py compare --tags prompt-v2 prompt-v3")
    base = Paths(args.baseline)
    others = [Paths(t) for t in tags]
    for p in [base] + others:
        if not p.summary_file.exists():
            die(f"找不到 {p.summary_file}。先对该运行执行 collect。")
    runs = [json.loads(p.summary_file.read_text(encoding="utf-8")) for p in [base] + others]
    keys = [k for k in runs[0]["models"] if all(k in s["models"] for s in runs) and (not args.models or k in args.models)]
    if not keys:
        die("这些运行没有共同的模型，无法对比。")
    title = "## Comparison: " + " vs ".join([base.tag or "baseline"] + tags)
    links = ", ".join(f"[docs/{p.eval_md.name}]({p.eval_md.name})" for p in others)
    note = (f"_Same {runs[0]['n_cases']} cases and {runs[0].get('reps', 3)} repeats; only the system prompt and the "
            f"'Satisfied when / Not a finding' lines in rules.md changed between runs. Full results of the tagged "
            f"runs: {links}._")
    body = "\n".join([title, "", note, "", *compare_markdown(runs, keys)])

    eval_text = base.eval_md.read_text(encoding="utf-8") if base.eval_md.exists() else "# Evaluation\n"
    base.eval_md.write_text(replace_block(eval_text, ek.COMPARE_START, ek.COMPARE_END, body, True), encoding="utf-8")
    print(f"对比表已写入 {base.eval_md}。")

    def arrow(key, fmt):
        return " → ".join(fmt(s["models"][k]["all"].get(key)) for s in runs)

    labels = " → ".join(run_label(s).split(" (")[0] for s in runs)
    readme = ek.README.read_text(encoding="utf-8")
    short = []
    for k in keys:
        short.append(f"_Prompt revisions ({labels}), {runs[0]['models'][k]['label']}: FP rate (critical/major) "
                     f"{arrow('fp_rate_major', ek.pct)}; clean cases wrongly flagged {arrow('clean_flagged_major', ek.pct)}; "
                     f"recall {arrow('recall', ek.pct)}. Details in [docs/eval.md](docs/eval.md#comparison)._")
    new = replace_block(readme, ek.README_COMPARE_START, ek.README_COMPARE_END, "\n".join(short), False)
    if new is None:
        print("README.md 里没有 <!-- eval-compare-start --> 标记，README 没有改。")
    else:
        ek.README.write_text(new, encoding="utf-8")
        print("README.md 里的对比说明已更新。")
    for k in keys:
        print(f"{runs[0]['models'][k]['label']}: 误报率(严重/主要) {arrow('fp_rate_major', ek.pct)}；"
              f"干净案例被冤枉 {arrow('clean_flagged_major', ek.pct)}；召回率 {arrow('recall', ek.pct)}")


# --------------------------------------------------------------------------- main


def main():
    global P
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--models", nargs="*", help=f"subset of: {' '.join(ek.MODELS)}")
        p.add_argument("--reps", type=int, default=3, help="repeats per case and model (default 3)")
        p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
        p.add_argument("--tag", help="keep this run separate under tests/results/TAG/ (e.g. after a prompt change)")

    p = sub.add_parser("estimate"); common(p)
    p.add_argument("--latency-n", type=int, default=0, help="also estimate a direct-call timing sample of N per model")
    p = sub.add_parser("submit"); common(p)
    p.add_argument("--force", action="store_true", help="start over even if batches.json already exists")
    p = sub.add_parser("status"); common(p)
    p = sub.add_parser("collect"); common(p)
    p.add_argument("--redownload", action="store_true", help="download results again even if raw files exist")
    p = sub.add_parser("score"); common(p)
    p = sub.add_parser("latency"); common(p)
    p.add_argument("--n", type=int, default=5, help="cases per model (default 5)")
    p = sub.add_parser("compare"); common(p)
    p.add_argument("--baseline", help="tag of the baseline run (default: the untagged baseline)")
    p.add_argument("--tags", nargs="+", help="one or more tagged runs to show side by side (instead of --tag)")

    args = ap.parse_args()
    P = Paths(args.tag)
    try:
        {"estimate": cmd_estimate, "submit": cmd_submit, "status": cmd_status, "collect": cmd_collect,
         "score": cmd_score, "latency": cmd_latency, "compare": cmd_compare}[args.cmd](args)
    except anthropic.AuthenticationError:
        die("API key 被拒绝：打开项目文件夹里的 .env，检查 ANTHROPIC_API_KEY= 后面的 key 是否完整"
            "（以 sk-ant- 开头），保存后再运行一次。")
    except anthropic.APIConnectionError:
        die("连不上 Anthropic（网络问题）。什么都没有丢：已提交的 Batch 和已下载的结果都还在，联网后再运行一次即可。")
    except anthropic.APIStatusError as e:
        die(f"Anthropic 返回错误 {e.status_code}：{e.message}\n稍后再运行一次即可，已提交的 Batch 和已下载的结果都不会丢。")


if __name__ == "__main__":
    main()
