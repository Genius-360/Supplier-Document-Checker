from streamlit.testing.v1 import AppTest

from conftest import ROOT


def test_app_runs_a_sample_and_handles_the_human_pause():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    assert not at.exception
    at.radio(key="mode").set_value("regex").run()
    sample = at.selectbox(key="sample")
    sample.select(next(o for o in sample.options if o.endswith("04"))).run()
    at.button(key="run").click().run()
    assert not at.exception
    assert any("Needs a person" in w.value for w in at.warning)         # paused, waiting for a person
    form_radio = [r for r in at.radio if r.label == "Your decision"][0]
    form_radio.set_value("approve")  # form widgets only count when set and submitted in the same run
    next(b for b in at.button if b.label == "Submit decision").click().run()
    assert not at.exception
    assert any("Approved by a person" in m.value for m in at.markdown)


def test_app_survives_llm_mode_without_a_key(monkeypatch, tmp_path):
    """Regression: llm mode with no key and an empty cache used to crash the page with KeyError: 'rule_results'."""
    monkeypatch.setenv("GEMINI_API_KEY", "")                     # empty = no key (and stops .env from re-adding one)
    monkeypatch.setenv("SUPPLIER_CHECK_CACHE_DIR", str(tmp_path))  # empty cache
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.run()
    at.radio(key="mode").set_value("llm").run()
    assert any("No Gemini key found" in w.value for w in at.sidebar.warning)
    at.button(key="run").click().run()
    assert not at.exception
    assert any("LLM unavailable" in w.value for w in at.warning)  # clear root cause, shown to the person
