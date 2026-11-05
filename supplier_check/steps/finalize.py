"""Step 8 - assemble the audit record for one document."""
from __future__ import annotations

from ..schemas import APPROVE, NEEDS_PERSON, REJECT


def final_status(verdict: str, human: dict | None) -> str:
    if verdict == APPROVE:
        return "Approved automatically"
    if verdict == REJECT:
        return "Rejected automatically"
    d = (human or {}).get("decision", "pending")
    return {"approve": "Approved by a person", "reject": "Rejected by a person"}.get(d, "Waiting for a person")


def finalize_node(state: dict) -> dict:
    facts = state.get("facts", {})
    get = lambda k: (facts.get(k) or {}).get("value")  # noqa: E731
    cmp = state.get("comparison") or {}
    human = state.get("human")
    record = {
        "doc_id": state.get("doc_id"),
        "supplier": get("supplier_name"),
        "item": get("item_code"),
        "system_verdict": state["verdict"],
        "primary_reason": state["primary_reason"],
        "reasons": state["reasons"],
        "human": human,
        "final_status": final_status(state["verdict"], human),
        "failed_rules": sorted(r["rule_id"] for r in state.get("rule_results", []) if r["status"] == "fail"),
        "unverified_rules": sorted(r["rule_id"] for r in state.get("rule_results", []) if r["status"] == "unknown"),
        "checks": [{"rule_id": r["rule_id"], "status": r["status"], "severity": r["severity"], "message": r["message"],
                    "evidence": r["evidence"]} for r in state.get("rule_results", [])],
        "comparison": cmp,
        "facts": facts,
        "verify_issues": state.get("verify_issues", []),
        "fatal_errors": state.get("fatal_errors", []),
        "trace": state.get("trace", []),
    }
    return {"record": record}
