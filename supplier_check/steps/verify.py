"""Step 3 - verify every extracted value against the document. This is the 'never guess' gate.

A value is only usable if:
  * its quote really appears in the document text,
  * the value really appears inside that quote,
  * and (when an LLM did the extraction) it agrees with the independent rule-based parser.
A claim that something is ABSENT (no TIN, no penalty clause, ...) is only accepted if a
scan of the whole document agrees. Anything else becomes `unknown`, which routes to a person.
"""
from __future__ import annotations

import re
import time

from ..fields import ENUM_VALUES, FIELD_SPECS, KIND
from ..schemas import Extraction, Fact
from ..textutil import digits, norm, numbers_in, to_decimal
from .regex_extractor import INCL_VAT, PENALTY_WORDS, context_line

CROSSCHECK = {
    "item_code", "pr_reference", "quantity", "unit_price", "line_amount", "subtotal", "vat_rate_pct",
    "vat_amount", "total", "price_includes_vat", "tin", "bin", "advance_pct", "payment_days_min",
    "payment_days_max", "delivery_value", "delivery_unit", "penalty_clause_present", "penalty_pct",
    "penalty_period", "penalty_base", "validity_days",
}
PENALTY_FIELDS = ("penalty_pct", "penalty_period", "penalty_base")
ENUM_TOKEN = {  # value -> word that must appear in the supporting quote
    "delivery_unit": {"days": "day", "weeks": "week", "months": "month"},
    "penalty_period": {"week": "week", "day": "day", "month": "month"},
    "penalty_base": {"order_value": "order value"},
}


def _unknown(src: str, why: str, quote: str | None = None) -> Fact:
    return Fact(value=None, quote=quote, status="unknown", reason=why, source=src)


def _tin_bin_present(text: str, which: str) -> bool:
    return bool(re.search(rf"\b{which}\b[^\n\d]{{0,25}}[\d-]{{6,}}", text, re.I))


def _ground(name: str, f: Fact, text: str) -> str | None:
    """Return a problem description, or None if the value is supported by its quote."""
    if not f.quote or not f.quote.strip():
        return "no supporting quote was given"
    if norm(f.quote) not in norm(text):
        return "the quote does not appear in the document"
    kind, v = KIND[name], f.value
    if kind == "number":
        if name == "advance_pct" and to_decimal(v) == 0:
            return None if re.search(r"\bno\s+advance\b", f.quote, re.I) else "a 0% advance is not supported by the quote"
        if to_decimal(v) not in numbers_in(f.quote):
            return "the value does not appear in the quote"
    elif kind == "text":
        if name in ("tin", "bin"):
            if digits(str(v)) not in digits(f.quote):
                return "the number does not appear in the quote"
        elif norm(str(v)) not in norm(f.quote):
            return "the value does not appear in the quote"
    elif kind == "bool":
        if name == "price_includes_vat" and v is True and not INCL_VAT.search(f.quote):
            return "the quote does not say that prices include VAT"
        if name == "penalty_clause_present" and v is True and not PENALTY_WORDS.search(f.quote):
            return "the quote does not mention a penalty or delay"
    elif kind == "enum":
        tok = ENUM_TOKEN.get(name, {}).get(v)
        if tok and tok not in norm(f.quote):
            return f"the quote does not contain '{tok}'"
    return None


def _same(name: str, a, b) -> bool:
    kind = KIND[name]
    if kind == "number":
        return to_decimal(a) == to_decimal(b)
    if kind == "text":
        return digits(str(a)) == digits(str(b)) if name in ("tin", "bin") else norm(str(a)) == norm(str(b))
    return a == b


def _verify_one(name: str, f: Fact, s: Fact | None, text: str, issues: list[str]) -> Fact:
    src = f.source
    shadow_has = s is not None and s.value is not None and s.value is not False
    v = f.value

    # --- claims that something is absent / false -------------------------------------------
    absence = v is None or v is False or (name == "penalty_base" and v == "not_stated")
    if absence:
        if f.reason:
            return _unknown(src, f.reason)
        if shadow_has and not (name == "penalty_base" and s.value == "not_stated"):
            issues.append(f"{name}: extractor found nothing but the rule-based parser found {s.value!r}")
            return _unknown(src, f"conflict: extractor found nothing but the rule-based parser found {s.value!r}")
        if name in ("tin", "bin"):
            if _tin_bin_present(text, name.upper()):
                return _unknown(src, f"conflict: {name.upper()} number appears in the text but was not extracted")
            return Fact(value=None, status="absent", source=src,
                        quote=context_line(text, r"regist|\bTIN\b|\bBIN\b"),
                        reason=f"no {name.upper()} number appears anywhere in the document")
        if name == "penalty_clause_present":
            if v is False and PENALTY_WORDS.search(text):
                return _unknown(src, "conflict: said there is no penalty clause but the text mentions a penalty/delay")
            if v is False:
                return Fact(value=False, status="ok", source=src, reason="no penalty/delay wording anywhere in the document")
        if name == "price_includes_vat" and v is False:
            if INCL_VAT.search(text):
                return _unknown(src, "conflict: said prices exclude VAT but the text says VAT/taxes are included")
            return Fact(value=False, status="ok", source=src)
        if name == "penalty_base" and v == "not_stated":
            if "order value" in norm(text):
                return _unknown(src, "conflict: said the penalty base is not stated but 'order value' appears in the text")
            return Fact(value="not_stated", status="ok", source=src, quote=f.quote)
        return _unknown(src, "not found in the document")

    # --- claims that a value exists: it must be grounded ------------------------------------
    problem = _ground(name, f, text)
    if problem:
        issues.append(f"{name}: {problem} (value given: {v!r})")
        return _unknown(src, f"not verified - {problem}", quote=f.quote)
    if s is not None and shadow_has and name in CROSSCHECK and not _same(name, v, s.value):
        issues.append(f"{name}: extractor says {v!r} but the rule-based parser says {s.value!r}")
        return _unknown(src, f"conflict: extractor says {v!r}, rule-based parser says {s.value!r}", quote=f.quote)
    return Fact(value=v, quote=f.quote, status="ok", source=src)


def verify_facts(primary: Extraction, shadow: Extraction, text: str, crosscheck: bool = True):
    issues: list[str] = []
    out: dict[str, Fact] = {}
    for name, _, _ in FIELD_SPECS:
        if primary.error:
            out[name] = _unknown(primary.extractor, f"extraction failed: {primary.error}")
            continue
        f = primary.facts.get(name, Fact(source=primary.extractor))
        s = shadow.facts.get(name) if crosscheck else None
        out[name] = _verify_one(name, f, s, text, issues)
    # if there is confirmed to be no penalty clause, the penalty details are simply not applicable
    pcp = out.get("penalty_clause_present")
    if pcp and pcp.status == "ok" and pcp.value is False:
        for n in PENALTY_FIELDS:
            out[n] = Fact(value=None, status="absent", source=pcp.source, reason="no penalty clause in the document")
    return out, issues


def make_verify_node(extractor: str):
    def verify_node(state: dict) -> dict:
        t0 = time.time()
        primary = Extraction(**state["primary"])
        shadow = Extraction(**state["shadow"])
        facts, issues = verify_facts(primary, shadow, state["raw_text"], crosscheck=(extractor != "regex"))
        n_ok = sum(1 for f in facts.values() if f.status == "ok")
        n_unknown = [k for k, f in facts.items() if f.status == "unknown"]
        msg = f"{n_ok} fields verified against the text"
        if n_unknown:
            msg += f"; {len(n_unknown)} could not be verified ({', '.join(n_unknown[:5])}{'...' if len(n_unknown) > 5 else ''})"
        return {
            "facts": {k: v.model_dump() for k, v in facts.items()},
            "verify_issues": issues,
            "trace": [{"step": "verify", "ok": not n_unknown, "summary": msg, "ms": int((time.time() - t0) * 1000)}],
        }
    return verify_node
