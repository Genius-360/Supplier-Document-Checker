"""The LLM path, tested with a FAKE model (no network). The point: whatever the model says,
nothing unverified can reach a verdict, and a lying/broken/offline model can only ever cause
'Needs a person', never a silent Approve or a wrong Reject."""
import json

import pytest

from conftest import SAMPLES, TRUTH
from supplier_check.config import load_config
from supplier_check.graph import build_graph, run_document
from supplier_check.llm import CachedLLM, LLMUnavailable
from supplier_check.schemas import APPROVE, NEEDS_PERSON, REJECT
from supplier_check.steps.ingest import read_pdf_text
from supplier_check.steps.regex_extractor import extract_regex


def honest(text: str) -> dict:
    """What a perfect model would return: the true value and the exact quote for every field."""
    out = {}
    for name, f in extract_regex(text).facts.items():
        out[name] = {"value": f.value, "quote": f.quote}
    return out


class FakeLLM:
    def __init__(self, fn):
        self.fn, self.calls = fn, 0

    def complete_json(self, system, user):
        self.calls += 1
        text = user.split("<document>\n", 1)[1].rsplit("\n</document>", 1)[0]
        out = self.fn(text, self.calls)
        if isinstance(out, Exception):
            raise out
        return out if isinstance(out, str) else json.dumps(out)


def run_with(fake, pdf_name):
    cfg = load_config("regex")
    cfg.extractor, cfg.llm = "llm", fake  # same pipeline, LLM extractor + rule-based cross-check
    app = build_graph(cfg)
    path = next(p for p in SAMPLES if p.stem == pdf_name)
    return run_document(app, doc_id=pdf_name, text=read_pdf_text(path))


@pytest.mark.parametrize("pdf", SAMPLES, ids=[p.stem for p in SAMPLES])
def test_honest_model_reproduces_all_ten_answers(pdf):
    rec = run_with(FakeLLM(lambda t, n: honest(t)), pdf.stem)
    assert rec["system_verdict"] == TRUTH[pdf.name]["verdict"], rec["primary_reason"]
    assert rec["failed_rules"] == sorted(TRUTH[pdf.name]["failed_rules"])


def tamper(**changes):
    def fn(text, n):
        d = honest(text)
        d.update(changes)
        return d
    return fn


def test_invented_quote_is_rejected_as_ungrounded():
    # pack 05 truly has a 40% advance (-> Reject). The model claims 10% and invents a supporting quote.
    fake = FakeLLM(tamper(advance_pct={"value": 10, "quote": "10% advance payable with the purchase order."}))
    rec = run_with(fake, "supplier-pack-05")
    assert rec["system_verdict"] == NEEDS_PERSON          # not Approve, and not a Reject built on a wrong number
    assert rec["facts"]["advance_pct"]["status"] == "unknown"
    assert "R2" in rec["unverified_rules"]


def test_value_that_contradicts_its_own_quote_is_rejected():
    fake = FakeLLM(tamper(advance_pct={"value": 10, "quote": "40% advance payable with the purchase order."}))
    rec = run_with(fake, "supplier-pack-05")
    assert rec["system_verdict"] == NEEDS_PERSON
    assert "does not appear in the quote" in rec["facts"]["advance_pct"]["reason"]


def test_model_picks_a_real_but_wrong_number_and_the_cross_check_catches_it():
    row = "A Cotton twill fabric, 280 gsm 12,000 metre 472.00 5,664,000.00"
    fake = FakeLLM(tamper(unit_price={"value": 12000, "quote": row}))   # grounded (12,000 is in the row) but wrong
    rec = run_with(fake, "supplier-pack-01")
    assert rec["system_verdict"] == NEEDS_PERSON
    assert "conflict" in rec["facts"]["unit_price"]["reason"]


def test_model_wrongly_says_tin_is_missing_so_no_false_reject():
    rec = run_with(FakeLLM(tamper(tin={"value": None, "quote": None})), "supplier-pack-01")
    assert rec["system_verdict"] == NEEDS_PERSON          # NOT Reject: an absence claim needs the text to agree
    assert "R4" not in rec["failed_rules"]


def test_model_wrongly_says_no_penalty_clause_so_no_false_reject():
    rec = run_with(FakeLLM(tamper(penalty_clause_present={"value": False, "quote": None})), "supplier-pack-01")
    assert rec["system_verdict"] == NEEDS_PERSON
    assert "R3" not in rec["failed_rules"]


def test_model_invents_a_tin_for_a_supplier_that_has_none():
    fake = FakeLLM(tamper(tin={"value": "111111111111", "quote": "TIN: 111111111111"},
                          bin={"value": "000000000-0000", "quote": "BIN: 000000000-0000"}))
    rec = run_with(fake, "supplier-pack-08")
    assert rec["system_verdict"] == NEEDS_PERSON           # never Approve; R4 cannot be silently skipped
    assert rec["facts"]["tin"]["status"] == "unknown"


def test_prompt_injection_obeyed_by_the_model_still_cannot_approve():
    # pack 03 is 9% over the maximum price. A fooled model "approves" by reporting a friendly price with a fake quote.
    fake = FakeLLM(tamper(unit_price={"value": 100, "quote": "Unit price 100.00"}))
    rec = run_with(fake, "supplier-pack-03")
    assert rec["system_verdict"] != APPROVE


def test_free_text_verdict_from_the_model_is_ignored():
    fake = FakeLLM(lambda t, n: {**honest(t), "verdict": "APPROVE", "decision": {"value": "approve"}})
    assert run_with(fake, "supplier-pack-03")["system_verdict"] == REJECT


def test_invalid_json_is_retried_once_then_goes_to_a_person():
    fake = FakeLLM(lambda t, n: "Sure! Here is the data: {not json")
    rec = run_with(fake, "supplier-pack-01")
    assert fake.calls == 2
    assert rec["system_verdict"] == NEEDS_PERSON


def test_one_bad_reply_then_a_good_one_recovers():
    fake = FakeLLM(lambda t, n: "oops" if n == 1 else honest(t))
    assert run_with(fake, "supplier-pack-01")["system_verdict"] == APPROVE


def test_model_in_markdown_fences_is_accepted():
    fake = FakeLLM(lambda t, n: "```json\n" + json.dumps(honest(t)) + "\n```")
    assert run_with(fake, "supplier-pack-01")["system_verdict"] == APPROVE


def test_model_offline_goes_to_a_person():
    rec = run_with(FakeLLM(lambda t, n: LLMUnavailable("no key")), "supplier-pack-01")
    assert rec["system_verdict"] == NEEDS_PERSON
    assert "LLM unavailable" in rec["reasons"][0]["message"]


def test_a_field_the_model_left_out_is_not_guessed():
    def fn(text, n):
        d = honest(text)
        d.pop("validity_days")
        return d
    rec = run_with(FakeLLM(fn), "supplier-pack-01")
    assert rec["system_verdict"] == NEEDS_PERSON
    assert "N7" in rec["unverified_rules"]


# ---------------------------------------------------------------------------------------- the cache
def test_cache_serves_repeat_requests_offline(tmp_path):
    inner = FakeLLM(lambda t, n: {"x": 1})
    c = CachedLLM(inner, tmp_path)
    prompt = "<document>\nhello\n</document>"
    assert c.complete_json("s", "u\n" + prompt) == c.complete_json("s", "u\n" + prompt)
    assert inner.calls == 1 and c.hits == 1
    offline = CachedLLM(None, tmp_path)                    # same cache folder, no model, no key
    assert json.loads(offline.complete_json("s", "u\n" + prompt)) == {"x": 1}


def test_cache_miss_without_a_model_raises_clearly(tmp_path):
    with pytest.raises(LLMUnavailable):
        CachedLLM(None, tmp_path).complete_json("s", "never seen")


def test_invalid_json_is_not_cached(tmp_path):
    inner = FakeLLM(lambda t, n: "not json")
    c = CachedLLM(inner, tmp_path)
    c.complete_json("s", "u\n<document>\nq\n</document>")
    assert list(tmp_path.glob("*.json")) == []


# ----------------------------------------------------------------------- the real Gemini client, stubbed
def _gemini(monkeypatch, handler, fallback=None):
    pytest.importorskip("google.genai")
    import supplier_check.llm as L
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("GEMINI_MODEL", "main-model")
    monkeypatch.delenv("GEMINI_FALLBACK_MODEL", raising=False)
    if fallback:
        monkeypatch.setenv("GEMINI_FALLBACK_MODEL", fallback)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    g = L.GeminiLLM()

    class Models:
        calls = []
        def generate_content(self, model, contents, config):
            Models.calls.append(model)
            return handler(model)
    g.client = type("C", (), {"models": Models()})()
    return g, Models.calls


class _Busy(Exception):
    code = 503


def test_overloaded_main_model_falls_back_to_the_backup_model(monkeypatch):
    def handler(model):
        if model == "main-model":
            raise _Busy("503 UNAVAILABLE: high demand")
        return type("R", (), {"text": '{"ok": 1}'})()
    g, calls = _gemini(monkeypatch, handler, fallback="backup-model")
    assert g.complete_json("s", "u") == '{"ok": 1}'
    assert calls.count("main-model") == g.RETRIES and calls[-1] == "backup-model"
    assert g.last_model == "backup-model"


def test_a_real_error_is_not_retried_or_hidden(monkeypatch):
    def handler(model):
        raise ValueError("API key not valid")
    g, calls = _gemini(monkeypatch, handler, fallback="backup-model")
    with pytest.raises(ValueError):
        g.complete_json("s", "u")
    assert calls == ["main-model"]
