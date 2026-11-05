"""Step 7 - stop and ask a person. Uses LangGraph's interrupt(): the run really pauses here."""
from __future__ import annotations

from langgraph.types import interrupt

DECISIONS = ("approve", "reject", "pending")


def human_review_node(state: dict) -> dict:
    payload = {
        "doc_id": state.get("doc_id"),
        "system_verdict": state["verdict"],
        "primary_reason": state["primary_reason"],
        "reasons": state["reasons"],
        "question": "The system is not sure and will not guess. Approve, reject, or leave it pending?",
    }
    answer = interrupt(payload)  # <- execution stops here until the graph is resumed with an answer
    if isinstance(answer, str):
        answer = {"decision": answer}
    decision = str((answer or {}).get("decision", "pending")).lower()
    if decision not in DECISIONS:
        decision = "pending"
    human = {"decision": decision, "reviewer": (answer or {}).get("reviewer"), "comment": (answer or {}).get("comment")}
    return {"human": human,
            "trace": [{"step": "human_review", "ok": True,
                       "summary": f"paused for a person; answer: {decision}"}]}
