"""Step 6 - the final answer. Fixed logic, no model involved."""
from __future__ import annotations

from ..schemas import APPROVE, NEEDS_PERSON, REJECT, RuleResult


def decide(results: list[RuleResult], fatal: list[str]) -> dict:
    if fatal:
        reasons = [{"rule_id": "INGEST", "status": "unknown", "severity": "needs_person", "message": m, "evidence": []}
                   for m in fatal]
        return {"verdict": NEEDS_PERSON, "reasons": reasons, "primary_reason": fatal[0]}

    fails_reject = [r for r in results if r.status == "fail" and r.severity == "reject"]
    fails_person = [r for r in results if r.status == "fail" and r.severity == "needs_person"]
    unknown = [r for r in results if r.status == "unknown"]

    if fails_reject:
        verdict, chosen = REJECT, fails_reject + fails_person  # report every failed rule, reject ones first
    elif fails_person or unknown:
        verdict, chosen = NEEDS_PERSON, fails_person + unknown
    else:
        passed = ", ".join(r.rule_id for r in results)
        return {"verdict": APPROVE, "reasons": [], "primary_reason": f"All {len(results)} checks passed ({passed})."}

    reasons = [{"rule_id": r.rule_id, "status": r.status, "severity": r.severity, "message": r.message,
                "rule": r.text, "evidence": r.evidence} for r in chosen]
    first = chosen[0]
    label = "could not be verified" if first.status == "unknown" else first.rule_id
    return {"verdict": verdict, "reasons": reasons, "primary_reason": f"{first.rule_id}: {first.message}"
            if first.status != "unknown" else f"{first.rule_id} {label}: {first.message}"}


def decide_node(state: dict) -> dict:
    results = [RuleResult(**r) for r in state.get("rule_results", [])]
    d = decide(results, state.get("fatal_errors", []))
    return {**d, "trace": [{"step": "decide", "ok": True, "summary": f"{d['verdict']} - {d['primary_reason']}"}]}
