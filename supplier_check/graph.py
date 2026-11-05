"""The pipeline as a LangGraph: clear fixed steps, one after another. No free-running agent.

    ingest -> extract -> verify -> match -> check_rules -> decide -> (human_review) -> finalize

The only branches are safety exits: an unreadable file or a failed extraction skips straight to
`decide`, and a "Needs a person" verdict pauses at `human_review`.
"""
from __future__ import annotations

import operator
import uuid
from typing import Annotated, Callable, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .config import PipelineConfig
from .schemas import NEEDS_PERSON
from .steps.decide import decide_node
from .steps.extract import make_extract_node
from .steps.finalize import finalize_node
from .steps.human_review import human_review_node
from .steps.ingest import ingest_node
from .steps.match import make_match_node
from .steps.rules import make_rules_node
from .steps.verify import make_verify_node

STEPS = ["ingest", "extract", "verify", "match", "check_rules", "decide", "human_review", "finalize"]


class State(TypedDict, total=False):
    doc_id: str
    pdf_path: str
    raw_text: str
    fatal_errors: Annotated[list, operator.add]
    primary: dict
    shadow: dict
    facts: dict
    verify_issues: list
    comparison: dict
    rule_results: list
    verdict: str
    reasons: list
    primary_reason: str
    human: dict
    record: dict
    trace: Annotated[list, operator.add]


def build_graph(cfg: PipelineConfig):
    g = StateGraph(State)
    g.add_node("ingest", ingest_node)
    g.add_node("extract", make_extract_node(cfg.extractor, cfg.llm))
    g.add_node("verify", make_verify_node(cfg.extractor))
    g.add_node("match", make_match_node(cfg.pr_lines, cfg.settings.get("vat_rate_pct", 15)))
    g.add_node("check_rules", make_rules_node(cfg.rules))
    g.add_node("decide", decide_node)
    g.add_node("human_review", human_review_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", lambda s: "decide" if s.get("fatal_errors") else "extract",
                            {"decide": "decide", "extract": "extract"})
    g.add_conditional_edges("extract", lambda s: "decide" if s.get("fatal_errors") else "verify",
                            {"decide": "decide", "verify": "verify"})
    g.add_edge("verify", "match")
    g.add_edge("match", "check_rules")
    g.add_edge("check_rules", "decide")
    g.add_conditional_edges("decide", lambda s: "human_review" if s["verdict"] == NEEDS_PERSON else "finalize",
                            {"human_review": "human_review", "finalize": "finalize"})
    g.add_edge("human_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=MemorySaver())


def pending_resolver(payload: dict) -> dict:
    """Non-interactive default: nobody is there to answer, so the document stays pending."""
    return {"decision": "pending", "reviewer": None, "comment": "no reviewer available in this run"}


def run_document(app, *, doc_id: str, pdf_path: str | None = None, text: str | None = None,
                 resolver: Callable[[dict], dict] | None = pending_resolver) -> dict:
    """Run one document through the graph, answering the human-review pause with `resolver`."""
    state: dict = {"doc_id": doc_id}
    if pdf_path:
        state["pdf_path"] = str(pdf_path)
    if text is not None:
        state["raw_text"] = text
    config = {"configurable": {"thread_id": f"{doc_id}-{uuid.uuid4().hex[:8]}"}}
    out = app.invoke(state, config)
    if "__interrupt__" in out:
        payload = out["__interrupt__"][0].value
        out = app.invoke(Command(resume=(resolver or pending_resolver)(payload)), config)
    return out["record"]
