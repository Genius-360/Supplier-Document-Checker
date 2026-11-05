"""Deterministic parser for the quotation layout.

It plays two roles: (1) the offline extractor when no LLM key is available, and
(2) an independent second opinion that is cross-checked against the LLM's answer.
Every quote it returns is a slice of the document, so it is grounded by construction.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..schemas import Extraction, Fact

ROW = re.compile(
    r"^(?P<code>[A-Z])\s+(?P<desc>.+?)\s+(?P<qty>\d[\d,]*(?:\.\d+)?)\s+(?P<unit>[A-Za-z]+)\s+"
    r"(?P<price>\d[\d,]*\.\d{2})\s+(?P<amount>\d[\d,]*\.\d{2})\s*$",
    re.M,
)
CLAUSE = re.compile(r"^\s*(\d+)\.\s+([A-Z][a-z]+)\.\s+(.*?)(?=^\s*\d+\.\s+[A-Z][a-z]+\.\s|\Z)", re.M | re.S)
INCL_VAT = re.compile(
    r"(?:VAT|tax(?:es)?)\W+(?:is\W+|are\W+)?(?:all\W+)?included|inclusive\s+of\s+(?:VAT|tax\w*)|all\s+taxes\s+included",
    re.I,
)
PENALTY_WORDS = re.compile(r"penalt|late\s+deliver|delay|liquidated", re.I)


def _num(s: str) -> float:
    return float(Decimal(s.replace(",", "")))


def _sentences(clause_text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", clause_text) if s.strip()]


def clauses(text: str, supplier: str | None = None) -> list[tuple[str, str]]:
    """Return [(heading, single-line clause text)] from the TERMS AND CONDITIONS block."""
    body = text.split("TERMS AND CONDITIONS", 1)[1] if "TERMS AND CONDITIONS" in text else text
    if supplier:  # drop the signature block ("For <supplier>")
        body = re.split(r"\n\s*For\s+" + re.escape(supplier), body)[0]
    out = []
    for m in CLAUSE.finditer(body):
        out.append((m.group(2), re.sub(r"\s+", " ", m.group(3)).strip()))
    return out


def context_line(text: str, pattern: str) -> str | None:
    for line in text.splitlines():
        if re.search(pattern, line, re.I):
            return line.strip()
    return None


def _F(value, quote, **kw) -> Fact:
    return Fact(value=value, quote=quote, source="regex", **kw)


def extract_regex(text: str) -> Extraction:
    f: dict[str, Fact] = {}
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)
    f["supplier_name"] = _F(first, first) if first else Fact(source="regex")

    m = re.search(r"Quotation\s+no\.?\s*(\S+)", text, re.I)
    f["quotation_no"] = _F(m.group(1), m.group(0)) if m else Fact(source="regex")
    m = re.search(r"\bDate\s+(\d{4}-\d{2}-\d{2})", text)
    f["quotation_date"] = _F(m.group(1), m.group(0)) if m else Fact(source="regex")
    m = re.search(r"Reference\s+(PR-[\w-]+)", text)
    f["pr_reference"] = _F(m.group(1), m.group(0)) if m else Fact(source="regex")

    # --- line item (the packs have exactly one) ---
    rows = list(ROW.finditer(text))
    item_fields = ["item_code", "item_description", "quantity", "unit", "unit_price", "line_amount"]
    if len(rows) == 1:
        r = rows[0]
        q = r.group(0).strip()
        f["item_code"] = _F(r["code"], q)
        f["item_description"] = _F(r["desc"].strip(), q)
        f["quantity"] = _F(_num(r["qty"]), q)
        f["unit"] = _F(r["unit"], q)
        f["unit_price"] = _F(_num(r["price"]), q)
        f["line_amount"] = _F(_num(r["amount"]), q)
    else:
        why = f"expected exactly one line-item row, found {len(rows)}"
        for k in item_fields:
            f[k] = Fact(source="regex", reason=why)

    # --- totals ---
    m = re.search(r"^Subtotal\s+(\d[\d,]*\.\d{2})\s*$", text, re.M)
    f["subtotal"] = _F(_num(m.group(1)), m.group(0).strip()) if m else Fact(source="regex")
    m = re.search(r"^VAT\s+(\d+(?:\.\d+)?)\s*%\s+(\d[\d,]*\.\d{2})\s*$", text, re.M)
    if m:
        f["vat_rate_pct"] = _F(_num(m.group(1)), m.group(0).strip())
        f["vat_amount"] = _F(_num(m.group(2)), m.group(0).strip())
    else:
        f["vat_rate_pct"] = Fact(source="regex")
        f["vat_amount"] = Fact(source="regex")
    m = re.search(r"^Total\b[^\n]*?(\d[\d,]*\.\d{2})\s*$", text, re.M)
    f["total"] = _F(_num(m.group(1)), m.group(0).strip()) if m else Fact(source="regex")

    m = INCL_VAT.search(text)
    if m:  # quote the whole line so the evidence is readable
        f["price_includes_vat"] = _F(True, context_line(text, INCL_VAT.pattern) or m.group(0))
    else:
        f["price_includes_vat"] = _F(False, None)

    m = re.search(r"\bTIN\s*[:#]?\s*([\d-]{6,})", text, re.I)
    f["tin"] = _F(m.group(1), m.group(0)) if m else Fact(source="regex")
    m = re.search(r"\bBIN\s*[:#]?\s*([\d-]{6,})", text, re.I)
    f["bin"] = _F(m.group(1), m.group(0)) if m else Fact(source="regex")

    # --- terms & conditions ---
    cl = {h.lower(): t for h, t in clauses(text, first)}

    # payment
    adv_vals: dict[Decimal, str] = {}
    pay = cl.get("payment")
    pdays = None
    if pay:
        for s in _sentences(pay):
            if re.search(r"\bno\s+advance\b", s, re.I):
                adv_vals.setdefault(Decimal(0), s)
            for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*advance", s, re.I):
                adv_vals.setdefault(Decimal(m.group(1)), s)
            m = re.search(r"within\s+(\d+)(?:\s*(?:to|-|\u2013)\s*(\d+))?\s+days", s, re.I)
            if m and pdays is None:
                pdays = (float(m.group(1)), float(m.group(2) or m.group(1)), s)
    if len(adv_vals) == 1:
        (v, s), = adv_vals.items()
        f["advance_pct"] = _F(float(v), s)
    elif len(adv_vals) > 1:
        f["advance_pct"] = Fact(source="regex", reason=f"conflicting advance percentages {sorted(map(str, adv_vals))}")
    else:
        f["advance_pct"] = Fact(source="regex")
    if pdays:
        f["payment_days_min"] = _F(pdays[0], pdays[2])
        f["payment_days_max"] = _F(pdays[1], pdays[2])
    else:
        f["payment_days_min"] = Fact(source="regex")
        f["payment_days_max"] = Fact(source="regex")

    # delivery
    f["delivery_value"] = Fact(source="regex")
    f["delivery_unit"] = Fact(source="regex")
    for s in _sentences(cl.get("delivery", "")):
        m = re.search(r"within\s+(\d+(?:\.\d+)?)\s+(day|week|month)s?", s, re.I)
        if m:
            f["delivery_value"] = _F(float(m.group(1)), s)
            f["delivery_unit"] = _F(m.group(2).lower() + "s", s)
            break

    # late-delivery penalty
    pen_text = None
    for head, t in cl.items():
        if head == "delay" or PENALTY_WORDS.search(t):
            pen_text = t
            break
    f["penalty_pct"] = Fact(source="regex")
    f["penalty_period"] = Fact(source="regex")
    f["penalty_base"] = Fact(source="regex")
    if pen_text is None:
        f["penalty_clause_present"] = _F(False, None)
    else:
        sents = _sentences(pen_text)
        psent = next((s for s in sents if "%" in s), sents[0] if sents else pen_text)
        f["penalty_clause_present"] = _F(True, psent)
        pcts = {m.group(1) for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", pen_text)}
        if len(pcts) == 1:
            f["penalty_pct"] = _F(float(next(iter(pcts))), psent)
        elif len(pcts) > 1:
            f["penalty_pct"] = Fact(source="regex", reason=f"several percentages in the penalty clause: {sorted(pcts)}")
        if len(pcts) >= 1:
            m = re.search(r"(?:per|each|every)\s+(?:full\s+)?(week|day|month)", psent, re.I)
            f["penalty_period"] = _F(m.group(1).lower(), psent) if m else _F("other", psent)
            if re.search(r"order\s+value", psent, re.I):
                f["penalty_base"] = _F("order_value", psent)
            else:
                f["penalty_base"] = _F("not_stated", None)

    # validity
    f["validity_days"] = Fact(source="regex")
    for s in _sentences(cl.get("validity", "")):
        m = re.search(r"valid\s+for\s+(\d+)\s+days", s, re.I)
        if m:
            f["validity_days"] = _F(float(m.group(1)), s)
            break

    return Extraction(extractor="regex", facts=f)
