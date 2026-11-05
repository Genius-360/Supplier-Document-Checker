from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ROOT, load_config
from .graph import build_graph, run_document

VERDICT_SHORT = {"Approve": "Approve", "Reject": "Reject", "Needs a person to check": "Needs a person"}


def interactive_resolver(payload: dict) -> dict:
    print("\n" + "=" * 72)
    print(f"A PERSON IS NEEDED for {payload['doc_id']}")
    print(f"System verdict: {payload['system_verdict']}")
    for r in payload["reasons"]:
        print(f"  - [{r['rule_id']}] {r['message']}")
        for e in r.get("evidence", []):
            print(f"        text: {e}")
    print(payload["question"])
    while True:
        a = input("  [a]pprove / [r]eject / [p]ending > ").strip().lower()[:1]
        if a in ("a", "r", "p"):
            break
    comment = input("  optional comment > ").strip() or None
    return {"decision": {"a": "approve", "r": "reject", "p": "pending"}[a], "reviewer": "cli", "comment": comment}


def write_outputs(records: list[dict], truth: dict | None, out: Path, extractor: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for r in records:
        (out / f"{r['doc_id']}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    rows, right, reasons_right = [], 0, 0
    for r in records:
        exp = (truth or {}).get(r["doc_id"] + ".pdf") or (truth or {}).get(r["doc_id"])
        v_ok = exp is not None and r["system_verdict"] == exp["verdict"]
        w_ok = exp is not None and sorted(exp["failed_rules"]) == r["failed_rules"]
        right += v_ok
        reasons_right += (v_ok and w_ok)
        rows.append({"doc_id": r["doc_id"], "item": r["item"], "verdict": r["system_verdict"],
                     "expected": exp["verdict"] if exp else None, "verdict_ok": v_ok if exp else None,
                     "failed_rules": r["failed_rules"], "expected_rules": exp["failed_rules"] if exp else None,
                     "rules_ok": w_ok if exp else None, "reason": r["primary_reason"],
                     "final_status": r["final_status"]})
    labels = ["Approve", "Reject", "Needs a person to check"]
    matrix = {e: {p: 0 for p in labels} for e in labels}
    for x in rows:
        if x["expected"] in matrix:
            matrix[x["expected"]][x["verdict"]] += 1
    summary = {"extractor": extractor, "confusion_matrix": matrix if truth else None, "documents": len(records), "verdict_correct": right if truth else None,
               "verdict_and_reasons_correct": reasons_right if truth else None, "rows": rows}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [f"# Results ({extractor} extractor)\n"]
    if truth:
        md.append(f"**Verdict correct: {right} of {len(records)}.** Verdict and exact set of failed rules both correct: "
                  f"{reasons_right} of {len(records)}.\n")
    if truth:
        md.append("**Confusion matrix** (rows = hand-labelled answer, columns = system verdict)\n")
        md.append("| expected \\ system | Approve | Reject | Needs a person |")
        md.append("|---|---|---|---|")
        for e in labels:
            md.append(f"| {e} | " + " | ".join(str(matrix[e][p]) for p in labels) + " |")
        md.append("")
    md.append("| Pack | Item | System verdict | Expected | Failed rules | Why |")
    md.append("|---|---|---|---|---|---|")
    for x in rows:
        mark = "" if x["verdict_ok"] is None else ("OK" if x["verdict_ok"] else "WRONG")
        md.append(f"| {x['doc_id']} | {x['item']} | {x['verdict']} | {x['expected'] or '-'} {mark} | "
                  f"{', '.join(x['failed_rules']) or '-'} | {x['reason'].replace('|', '/')} |")
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="supplier_check", description="Check supplier quotations step by step. Never guesses.")
    ap.add_argument("--samples", default=str(ROOT / "data" / "samples"), help="folder with the supplier-pack PDFs")
    ap.add_argument("--file", help="run a single PDF instead of the whole folder")
    ap.add_argument("--extractor", default="auto", choices=["auto", "llm", "regex"],
                    help="auto = llm if GEMINI_API_KEY is set, else the offline rule-based parser")
    ap.add_argument("--rules", default=str(ROOT / "rules.yaml"))
    ap.add_argument("--purchase-request", default=str(ROOT / "data" / "purchase-request.csv"))
    ap.add_argument("--truth", default=str(ROOT / "data" / "ground_truth.json"), help="expected answers, for scoring")
    ap.add_argument("--out", default=None, help="where to write results (default: results/<extractor>/)")
    ap.add_argument("--interactive", action="store_true", help="actually ask a person when the system is unsure")
    ap.add_argument("--refresh", action="store_true", help="ignore the LLM cache and call the model again")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.extractor, args.rules, args.purchase_request, refresh=args.refresh)
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(f"Setup problem: {e}", file=sys.stderr)
        return 2
    app = build_graph(cfg)
    out_dir = Path(args.out) if args.out else ROOT / "results" / cfg.extractor
    files = [Path(args.file)] if args.file else sorted(Path(args.samples).glob("supplier-pack-*.pdf"))
    if not files:
        print(f"No PDFs found in {args.samples}", file=sys.stderr)
        return 2
    truth = None
    if not args.file and Path(args.truth).exists():
        truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))

    note = ""
    if args.extractor == "auto" and cfg.extractor == "regex":
        note = "  (no GEMINI_API_KEY found: using the offline rule-based parser)"
    elif cfg.extractor == "llm" and not os.getenv("GEMINI_API_KEY"):
        note = "  (WARNING: no GEMINI_API_KEY found; only cached model answers can be used)"
    print(f"Extractor: {cfg.extractor}{note}")
    records = []
    for f in files:
        rec = run_document(app, doc_id=f.stem, pdf_path=str(f),
                           resolver=interactive_resolver if args.interactive else None)
        records.append(rec)
        tail = f"   -> {rec['final_status']}" if rec.get("human") else ""
        print(f"{f.stem:<18} {rec['item'] or '?':<2} {VERDICT_SHORT[rec['system_verdict']]:<15} {rec['primary_reason']}{tail}")
    summary = write_outputs(records, truth, out_dir, cfg.extractor)
    if truth:
        print(f"\nVerdict correct: {summary['verdict_correct']}/{summary['documents']}   "
              f"(exact failed-rule set also correct: {summary['verdict_and_reasons_correct']}/{summary['documents']})")
    print(f"Results written to {out_dir}/ (summary.md + one JSON audit record per document)")
    if cfg.llm is not None and hasattr(cfg.llm, "hits"):
        print(f"LLM calls this run: {cfg.llm.calls} (served from cache: {cfg.llm.hits})")
    return 0
