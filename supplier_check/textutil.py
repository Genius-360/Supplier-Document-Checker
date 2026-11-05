from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def norm(s: str | None) -> str:
    """Lower-case, unify quotes and collapse all whitespace (PDF line breaks included)."""
    s = (s or "")
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u00a0", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def numbers_in(s: str | None) -> list[Decimal]:
    out = []
    for m in _NUM.finditer(s or ""):
        try:
            out.append(Decimal(m.group(0).replace(",", "")))
        except InvalidOperation:
            pass
    return out


def to_decimal(v) -> Decimal:
    """Exact decimal from a float/int/str (str(float) gives the shortest exact repr)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, str):
        v = v.replace(",", "").strip()
    return Decimal(str(v))


def digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def fmt(d: Decimal, places: int = 2) -> str:
    return f"{d:,.{places}f}"
