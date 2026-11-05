"""The 10 sample packs, scored against the hand-labelled answers."""
import pytest

from conftest import SAMPLES, TRUTH
from supplier_check.graph import run_document


@pytest.mark.parametrize("pdf", SAMPLES, ids=[p.stem for p in SAMPLES])
def test_sample_pack(app, pdf):
    rec = run_document(app, doc_id=pdf.stem, pdf_path=str(pdf))
    exp = TRUTH[pdf.name]
    assert rec["system_verdict"] == exp["verdict"], rec["primary_reason"]
    assert rec["failed_rules"] == sorted(exp["failed_rules"])


def test_every_rejection_and_review_comes_with_quoted_evidence(app):
    for pdf in SAMPLES:
        rec = run_document(app, doc_id=pdf.stem, pdf_path=str(pdf))
        for r in rec["reasons"]:
            assert r["evidence"], f"{pdf.stem} {r['rule_id']} has no supporting text"
