import copy

import pytest
import yaml

from conftest import ROOT, SAMPLES
from supplier_check.config import load_config
from supplier_check.graph import build_graph, run_document
from supplier_check.schemas import APPROVE, NEEDS_PERSON, REJECT
from supplier_check.steps.rules import load_rules, validate_rules


def pdf(name):
    return str(next(p for p in SAMPLES if p.stem == name))


# ------------------------------------------------------------------------------------ human review
def test_graph_really_pauses_and_waits_for_a_person(app):
    cfg = {"configurable": {"thread_id": "pause-test"}}
    out = app.invoke({"doc_id": "p4", "pdf_path": pdf("supplier-pack-04")}, cfg)
    assert "__interrupt__" in out
    assert app.get_state(cfg).next == ("human_review",)
    assert out["__interrupt__"][0].value["system_verdict"] == NEEDS_PERSON


def test_person_decision_is_recorded_without_rewriting_the_system_verdict(app):
    rec = run_document(app, doc_id="p4", pdf_path=pdf("supplier-pack-04"),
                       resolver=lambda payload: {"decision": "approve", "reviewer": "Rahim", "comment": "price is fine"})
    assert rec["system_verdict"] == NEEDS_PERSON
    assert rec["human"]["decision"] == "approve" and rec["human"]["reviewer"] == "Rahim"
    assert rec["final_status"] == "Approved by a person"


def test_no_reviewer_means_pending_not_a_guess(app):
    rec = run_document(app, doc_id="p4", pdf_path=pdf("supplier-pack-04"))
    assert rec["human"]["decision"] == "pending" and rec["final_status"] == "Waiting for a person"


def test_nonsense_from_the_reviewer_becomes_pending(app):
    rec = run_document(app, doc_id="p4", pdf_path=pdf("supplier-pack-04"), resolver=lambda p: {"decision": "yolo"})
    assert rec["human"]["decision"] == "pending"


def test_a_person_is_only_asked_when_needed(app):
    def boom(payload):
        raise AssertionError("a person should not be asked about an Approve or a Reject")
    for name in ("supplier-pack-01", "supplier-pack-03"):
        run_document(app, doc_id=name, pdf_path=pdf(name), resolver=boom)


# ---------------------------------------------------------------------------------- rules are data
def cfg_with(tmp_path, edit):
    data = yaml.safe_load((ROOT / "rules.yaml").read_text(encoding="utf-8"))
    edit(data)
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return build_graph(load_config("regex", rules_path=p))


def rule(data, rid):
    return next(r for r in data["rules"] if r["id"] == rid)


def test_changing_a_number_in_rules_yaml_changes_the_outcome(tmp_path):
    # pack 05 has a 40% advance -> Reject under the default 20% limit; allow 45% and it is Approve.
    app = cfg_with(tmp_path, lambda d: rule(d, "R2")["params"].update(max_pct=45))
    assert run_document(app, doc_id="p5", pdf_path=pdf("supplier-pack-05"))["system_verdict"] == APPROVE


def test_disabling_a_rule_in_rules_yaml(tmp_path):
    app = cfg_with(tmp_path, lambda d: rule(d, "R3").update(enabled=False))
    assert run_document(app, doc_id="p6", pdf_path=pdf("supplier-pack-06"))["system_verdict"] == APPROVE


def test_moving_a_rule_from_reject_to_needs_person(tmp_path):
    app = cfg_with(tmp_path, lambda d: rule(d, "R1").update(severity="needs_person"))
    assert run_document(app, doc_id="p3", pdf_path=pdf("supplier-pack-03"))["system_verdict"] == NEEDS_PERSON


def test_bad_rules_file_fails_with_a_clear_message():
    with pytest.raises(ValueError, match="unknown check"):
        validate_rules([{"id": "X", "check": "does_not_exist", "severity": "reject"}])
    with pytest.raises(ValueError, match="duplicate"):
        r = {"id": "X", "check": "advance_over", "severity": "reject"}
        validate_rules([r, copy.deepcopy(r)])
    with pytest.raises(ValueError, match="severity"):
        validate_rules([{"id": "X", "check": "advance_over", "severity": "maybe"}])
    rules, _ = load_rules(ROOT / "rules.yaml")
    assert len(rules) == 13
