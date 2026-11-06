"""Demo UI:  streamlit run app.py
Pick a sample pack (or upload a PDF), watch it go through the fixed steps, see the exact text behind every
decision, and answer the 'needs a person' pause yourself."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import streamlit as st
from langgraph.types import Command

from supplier_check.config import ROOT, load_config
from supplier_check.graph import STEPS, build_graph, run_document
from supplier_check.schemas import APPROVE, NEEDS_PERSON, REJECT

st.set_page_config(page_title="Supplier document checker", layout="wide")
SAMPLES = sorted((ROOT / "data" / "samples").glob("supplier-pack-*.pdf"))
TRUTH = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))


@st.cache_resource
def get_app(mode: str):
    cfg = load_config(mode)
    return cfg, build_graph(cfg)


st.title("Supplier document checker")
st.caption("Fixed steps, one after another. It never guesses: anything it cannot verify goes to a person.")
mode = st.sidebar.radio("Extractor", ["auto", "regex", "llm"], key="mode",
                        help="auto = Gemini if GEMINI_API_KEY is set, otherwise the offline rule-based parser. "
                             "llm = Gemini (or cached answers) cross-checked by the rule-based parser.")
cfg, app = get_app(mode)
st.sidebar.write(f"Running with: **{cfg.extractor}**")
_key = bool(os.getenv("GEMINI_API_KEY"))
_env = (ROOT / ".env").exists()
_cached = len(list(Path(getattr(cfg.llm, "dir", ROOT / "cache" / "llm")).glob("*.json"))) if cfg.llm else 0
st.sidebar.caption(f"Gemini key: {'found' if _key else 'NOT found'}  \n.env file: {'found' if _env else 'not found'}"
                   + (f"  \ncached model answers: {_cached}" if cfg.llm else ""))
if cfg.extractor == "llm" and not _key:
    st.sidebar.warning("No Gemini key found, so only cached answers can be used. Create a .env file next to app.py "
                       "with GEMINI_API_KEY=your-key, then restart Streamlit.")
st.sidebar.markdown("**Pipeline**  \n" + "  \n".join(f"{i}. {s}" for i, s in enumerate(STEPS, 1)))

ICON = {"pass": "PASS", "fail": "FAIL", "unknown": "UNVERIFIED"}


def banner(verdict: str, reason: str):
    {APPROVE: st.success, REJECT: st.error, NEEDS_PERSON: st.warning}[verdict](f"**{verdict}**  \n{reason}")


def details(reasons, checks, facts, comparison, trace):
    if not checks:
        st.info("The rule checks did not run because the document could not be read reliably (see the reason above).")
    t1, t2, t3, t4, t5 = st.tabs(["Why", "All checks", "What was read", "Vs purchase request", "Steps"])
    with t1:
        if not reasons:
            st.write("Every check passed.")
        for r in reasons:
            st.markdown(f"**{r['rule_id']}** ({r['status']}): {r['message']}")
            if r.get("rule"):
                st.caption(f"Rule: {r['rule']}")
            for e in r.get("evidence", []):
                st.code(e, language=None)
    with t2:
        st.dataframe([{"rule": c["rule_id"], "result": ICON[c["status"]], "severity": c["severity"],
                       "detail": c["message"]} for c in checks], hide_index=True, width="stretch")
    with t3:
        st.dataframe([{"field": k, "value": "" if v["value"] is None else str(v["value"]), "status": v["status"],
                       "supporting text": v["quote"] or v["reason"] or ""} for k, v in facts.items()],
                     hide_index=True, width="stretch")
    with t4:
        st.json(comparison)
    with t5:
        st.dataframe([{"step": t["step"], "ok": t["ok"], "what happened": t["summary"], "ms": str(t.get("ms", ""))}
                      for t in trace], hide_index=True, width="stretch")


tab_one, tab_all = st.tabs(["Check one document", "Run all 10 samples"])

with tab_one:
    src = st.radio("Document", ["Sample pack", "Upload a PDF"], horizontal=True, key="src")
    path, name = None, None
    if src == "Sample pack":
        pick = st.selectbox("Sample", SAMPLES, format_func=lambda p: p.stem, key="sample")
        path, name = str(pick), pick.stem
    else:
        up = st.file_uploader("Supplier quotation (PDF with a text layer)", type=["pdf"], key="upload")
        if up:
            tmp = Path(tempfile.mkdtemp()) / up.name
            tmp.write_bytes(up.getvalue())
            path, name = str(tmp), Path(up.name).stem

    if st.button("Check document", type="primary", disabled=path is None, key="run"):
        thread = {"configurable": {"thread_id": f"{name}-{uuid.uuid4().hex[:8]}"}}
        st.session_state.thread = thread
        st.session_state.out = app.invoke({"doc_id": name, "pdf_path": path}, thread)

    out = st.session_state.get("out")
    if out:
        if "__interrupt__" in out:  # the graph is paused at human_review
            payload = out["__interrupt__"][0].value
            banner(out["verdict"], out["primary_reason"])
            st.subheader("A person is needed")
            st.write(payload["question"])
            with st.form("review"):
                decision = st.radio("Your decision", ["approve", "reject", "pending"], horizontal=True, index=2)
                who = st.text_input("Your name")
                note = st.text_input("Comment")
                if st.form_submit_button("Submit decision"):
                    st.session_state.out = app.invoke(
                        Command(resume={"decision": decision, "reviewer": who or None, "comment": note or None}),
                        st.session_state.thread)
                    st.rerun()
            details(out.get("reasons", []), out.get("rule_results", []), out.get("facts", {}),
                    out.get("comparison", {}), out.get("trace", []))
        else:
            rec = out["record"]
            banner(rec["system_verdict"], rec["primary_reason"])
            st.write(f"**Status:** {rec['final_status']}")
            if rec.get("human"):
                st.write(f"Person's decision: **{rec['human']['decision']}**"
                         + (f" by {rec['human']['reviewer']}" if rec["human"].get("reviewer") else ""))
            exp = TRUTH.get(rec["doc_id"] + ".pdf")
            if exp:
                st.caption(f"Hand-labelled answer: {exp['verdict']} - "
                           + ("matches." if exp["verdict"] == rec["system_verdict"] else "DOES NOT MATCH."))
            details(rec["reasons"], rec["checks"], rec["facts"], rec["comparison"], rec["trace"])

with tab_all:
    if st.button("Run all 10 samples", key="run_all"):
        rows, right = [], 0
        for p in SAMPLES:
            rec = run_document(app, doc_id=p.stem, pdf_path=str(p))
            exp = TRUTH[p.name]
            ok = rec["system_verdict"] == exp["verdict"] and rec["failed_rules"] == sorted(exp["failed_rules"])
            right += ok
            rows.append({"pack": p.stem, "item": rec["item"], "verdict": rec["system_verdict"],
                         "expected": exp["verdict"], "correct": "yes" if ok else "NO", "why": rec["primary_reason"]})
        st.metric("Correct (verdict and rules)", f"{right} / {len(SAMPLES)}")
        st.dataframe(rows, hide_index=True, width="stretch")
