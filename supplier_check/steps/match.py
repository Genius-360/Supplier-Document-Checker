"""Step 4 - compare the quote with the purchase request (quantity and price). Pure code, no LLM."""
from __future__ import annotations

import csv
import re
import time
from decimal import Decimal
from pathlib import Path

from ..schemas import Fact
from ..textutil import norm, to_decimal


def load_purchase_request(path: str | Path) -> dict[tuple[str, str], dict]:
    lines = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            key = (row["PR number"].strip().upper(), row["Item"].strip().upper())
            lines[key] = {
                "pr": key[0],
                "item": key[1],
                "description": row["Description"].strip(),
                "unit": row["Unit"].strip(),
                "quantity_requested": str(to_decimal(row["Quantity requested"])),
                "max_unit_price": str(to_decimal(row["Maximum unit price (BDT)"])),
            }
    return lines


def _ok(facts: dict[str, Fact], *names: str) -> bool:
    return all(facts[n].status == "ok" and facts[n].value is not None for n in names)


def _simple(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", norm(s))


def compare_to_request(facts: dict[str, Fact], pr_lines: dict, vat_rate_pct) -> dict:
    out: dict = {"matched": False, "reason": None}
    if not _ok(facts, "pr_reference", "item_code"):
        out["reason"] = "the purchase-request reference or item letter could not be read reliably"
        return out
    key = (str(facts["pr_reference"].value).strip().upper(), str(facts["item_code"].value).strip().upper())
    line = pr_lines.get(key)
    if line is None:
        out["reason"] = f"purchase request has no line {key[1]} under {key[0]}"
        return out
    if not _ok(facts, "item_description", "unit"):
        out["reason"] = "the item description or unit could not be read reliably"
        return out
    if _simple(facts["item_description"].value) != _simple(line["description"]):
        out["reason"] = (f"quoted item '{facts['item_description'].value}' does not match requested "
                         f"'{line['description']}'")
        return out
    if _simple(facts["unit"].value) != _simple(line["unit"]):
        out["reason"] = f"quoted unit '{facts['unit'].value}' differs from requested unit '{line['unit']}'"
        return out

    out.update(matched=True, pr_line=line, qty_requested=line["quantity_requested"], max_price=line["max_unit_price"])
    if _ok(facts, "quantity"):
        req, got = Decimal(line["quantity_requested"]), to_decimal(facts["quantity"].value)
        out["qty_quoted"] = str(got)
        out["qty_diff"] = str(got - req)
        out["qty_dev_pct"] = str((got - req) / req * 100)  # signed, full precision
    if _ok(facts, "unit_price"):
        mx, p = Decimal(line["max_unit_price"]), to_decimal(facts["unit_price"].value)
        out["price_quoted"] = str(p)
        out["price_over_max_pct"] = str((p - mx) / mx * 100)  # negative = under the maximum
        vat = Decimal(str(vat_rate_pct)) / 100
        out["price_over_max_pct_ex_vat"] = str((p / (1 + vat) - mx) / mx * 100)  # if the price already includes VAT
    return out


def make_match_node(pr_lines: dict, vat_rate_pct):
    def match_node(state: dict) -> dict:
        t0 = time.time()
        facts = {k: Fact(**v) for k, v in state["facts"].items()}
        cmp = compare_to_request(facts, pr_lines, vat_rate_pct)
        if cmp["matched"]:
            bits = []
            if "qty_dev_pct" in cmp:
                bits.append(f"quantity {Decimal(cmp['qty_dev_pct']):+.2f}% vs requested")
            if "price_over_max_pct" in cmp:
                bits.append(f"price {Decimal(cmp['price_over_max_pct']):+.2f}% vs maximum")
            msg = f"matched to PR line {cmp['pr_line']['pr']}/{cmp['pr_line']['item']}: " + "; ".join(bits)
        else:
            msg = f"could not match to the purchase request: {cmp['reason']}"
        return {"comparison": cmp, "trace": [{"step": "match", "ok": cmp["matched"], "summary": msg,
                                              "ms": int((time.time() - t0) * 1000)}]}
    return match_node
