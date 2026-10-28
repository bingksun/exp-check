"""exp-check - Streamlit web interface.

Run with:  python -m streamlit run app.py
"""

import streamlit as st

from checker import (
    SEVERITIES,
    CheckError,
    count_rules,
    get_api_key,
    load_config,
    load_rules,
    report_to_markdown,
    run_check,
)

st.set_page_config(page_title="exp-check", page_icon="🔬", layout="wide")

EXAMPLE_TEXT = """Methods. HeLa cells were transfected with siRNA against GENE-X (Dharmacon) using \
Lipofectamine RNAiMAX. After 48 h, cells were lysed and GENE-X levels were analysed by western \
blot. Cell migration was measured by scratch assay at 0 and 24 h and the open wound area was \
quantified in ImageJ. Knockdown of GENE-X reduced migration by 45% (p < 0.05, Student's t-test, \
n = 3 wells). Data are shown as mean ± error bars."""

SEVERITY_STYLE = {
    "critical": ("🔴", "Critical"),
    "major": ("🟠", "Major"),
    "minor": ("🟡", "Minor"),
}

# ----------------------------------------------------------------------------- load settings

try:
    cfg = load_config()
    rules_text = load_rules(cfg)
except CheckError as e:
    st.error(str(e))
    st.stop()

api_key = get_api_key()

# ----------------------------------------------------------------------------- sidebar

with st.sidebar:
    st.header("Settings")
    st.markdown(
        f"**Model:** `{cfg['model']}`  \n"
        f"**Effort:** {cfg['effort']}  \n"
        f"**Rules loaded:** {count_rules(rules_text)}"
    )
    st.caption("Change the model in `config.toml`. Add or edit rules in `rules.md`.")
    if api_key:
        st.success("API key loaded from .env")
    else:
        st.error(
            "No API key found. Open the file `.env` in a text editor, paste your key after "
            "`ANTHROPIC_API_KEY=`, save, then click **Check**."
        )
    with st.expander("Current rules"):
        st.markdown(rules_text)

# ----------------------------------------------------------------------------- main panel

st.title("🔬 exp-check")
st.markdown(
    "Paste a **protocol**, a **Methods paragraph**, or a **figure legend**. exp-check reviews it "
    "against the rules in `rules.md` and reports missing controls, sample-size and statistics "
    "mismatches, and RNAi / CRISPR-specific gaps - each with a severity and a suggested fix."
)

if "text" not in st.session_state:
    st.session_state.text = ""
if "report" not in st.session_state:
    st.session_state.report = None
if "checked_text" not in st.session_state:
    st.session_state.checked_text = ""

top_left, top_right = st.columns([3, 1])
with top_left:
    text_type = st.selectbox(
        "What is this text?",
        ["Auto-detect", "Protocol", "Methods section", "Figure legend"],
    )
with top_right:
    st.write("")  # vertical alignment
    if st.button("Load example", help="Fill the box with a deliberately flawed Methods paragraph"):
        st.session_state.text = EXAMPLE_TEXT
        st.session_state.report = None

text = st.text_area(
    "Text to check",
    key="text",
    height=280,
    placeholder="Paste your protocol, methods paragraph or figure legend here...",
)

run = st.button("Check", type="primary", disabled=not text.strip())

if run:
    if not api_key:
        st.error("Add your API key to `.env` first (see the left panel).")
        st.stop()
    with st.spinner("Reviewing against the rules... this usually takes 20-60 seconds."):
        try:
            st.session_state.report = run_check(text, text_type, cfg, rules_text, api_key)
            st.session_state.checked_text = text
        except CheckError as e:
            st.session_state.report = None
            st.error(str(e))

# ----------------------------------------------------------------------------- report

report = st.session_state.report
if report:
    findings = report["findings"]
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}

    st.divider()
    st.subheader("Report")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Critical", counts["critical"])
    m2.metric("Major", counts["major"])
    m3.metric("Minor", counts["minor"])
    m4.metric("Rules satisfied", len(report["satisfied"]))

    detected = ", ".join(report.get("experiments_detected", [])) or "not identified"
    st.markdown(
        f"**Detected:** {detected}  \n"
        f"**Text type:** {report.get('text_type', '').replace('_', ' ')}"
    )
    st.info(report.get("overall_assessment", ""))

    if not findings:
        st.success("No problems found against the current rules.")

    for f in findings:
        icon, label = SEVERITY_STYLE[f["severity"]]
        with st.container(border=True):
            st.markdown(f"#### {icon} {label} · {f['rule_id']} - {f['title']}")
            st.markdown(f"**Issue:** {f['issue']}")
            st.markdown(f"**Why reviewers care:** {f['why_reviewers_care']}")
            st.markdown(f"**Suggested fix:** {f['suggestion']}")
            if f.get("evidence"):
                st.caption(f"From the text: “{f['evidence']}”")

    if report["satisfied"]:
        with st.expander(f"Rules satisfied ({len(report['satisfied'])})"):
            for s in report["satisfied"]:
                st.markdown(f"- **{s['rule_id']}** - {s['note']}")
    if report["not_applicable"]:
        with st.expander(f"Rules not applicable to this text ({len(report['not_applicable'])})"):
            st.markdown(", ".join(report["not_applicable"]))
    if report.get("notes"):
        st.markdown(f"**Notes (not rule violations):** {report['notes']}")

    meta = report.get("_meta", {})
    if meta:
        st.caption(
            f"Model: {meta.get('model')} · input tokens: {meta.get('input_tokens')} · "
            f"output tokens: {meta.get('output_tokens')}"
        )

    st.download_button(
        "Download report (.md)",
        data=report_to_markdown(report, st.session_state.checked_text),
        file_name="exp-check-report.md",
        mime="text/markdown",
    )

st.divider()
st.caption(
    "exp-check is an AI-assisted checklist, not a substitute for a statistician or a "
    "domain expert. The text you paste is sent to the Anthropic API for analysis."
)
