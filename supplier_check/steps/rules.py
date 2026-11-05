"""Step 5 - apply the company rules. Pure code, tri-state: pass / fail / unknown.

`unknown` means "a fact this rule needs could not be verified". It is never turned into a guess;
the decision step sends any unknown to a person.
"""
from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import yaml

from ..schemas import Fact, RuleResult
from ..textutil import to_decimal
from .regex_extractor import clauses


def D(v) -> Decimal:
    return to_decimal(v)


def n(d: Decimal) -> str:
    """Readable decimal: thousands separators, no trailing zeros, no exponent."""
    return format(Decimal(d).normalize(), ",f")


class Ctx:
    def __init__(self, facts: dict[str, Fact], cmp: dict, text: str):
        self.facts, self.cmp, self.text = facts, cmp, text

    def ok(self, *names: str) -> bool:
        return all(self.facts[x].status == "ok" and self.facts[x].value is not None for x in names)

    def val(self, name: str):
        return self.facts[name].value

    def num(self, name: str) -> Decimal:
        return D(self.facts[name].value)

    def why(self, *names: str) -> str:
        bits = [f"{x}: {self.facts[x].reason or 'not found'}" for x in names if not self.ok(x)]
        return "; ".join(bits) or "required values missing"

    def quotes(self, *names: str) -> list[str]:
        seen, out = set(), []
        for x in names:
            q = self.facts[x].quote
            if q and q not in seen:
                seen.add(q)
                out.append(q)
        return out

    def outline(self) -> str:
        sup = self.facts["supplier_name"].value if self.ok("supplier_name") else None
        heads = [f"{i}. {h}" for i, (h, _) in enumerate(clauses(self.text, sup), 1)]
        return "; ".join(heads) or "(no numbered clauses found)"


def _res(rule: dict, status: str, message: str, evidence=()) -> RuleResult:
    return RuleResult(rule_id=rule["id"], check=rule["check"], severity=rule["severity"], status=status,
                      message=message, text=rule.get("text", ""), evidence=[e for e in evidence if e])


def _p(rule: dict) -> dict:
    return rule.get("params") or {}


# ----------------------------------------------------------------------------------------- checks
def price_over_max(ctx: Ctx, rule: dict) -> RuleResult:
    p = _p(rule)
    lo = D(p.get("over_pct_gt", 0))
    hi = D(p["over_pct_lte"]) if p.get("over_pct_lte") is not None else None
    if not ctx.cmp.get("matched"):
        return _res(rule, "unknown", f"Cannot compare the price: {ctx.cmp.get('reason')}.")
    if not ctx.ok("unit_price", "price_includes_vat"):
        return _res(rule, "unknown", f"Unit price not verified ({ctx.why('unit_price', 'price_includes_vat')}).")

    def hit(pct: Decimal) -> bool:
        return pct > lo and (hi is None or pct <= hi)

    mx, price = D(ctx.cmp["max_price"]), ctx.num("unit_price")
    over = D(ctx.cmp["price_over_max_pct"])
    ev = ctx.quotes("unit_price") + [f"purchase-request.csv: maximum unit price {n(mx)} BDT"]
    if ctx.val("price_includes_vat") is True:  # max-price basis (with/without VAT) is not stated
        over_ex = D(ctx.cmp["price_over_max_pct_ex_vat"])
        a, b = hit(over), hit(over_ex)
        if a and b:
            return _res(rule, "fail", f"Unit price {n(price)} (VAT included) is above the maximum {n(mx)} on either VAT basis.", ev)
        if a or b:
            return _res(rule, "unknown", f"Unit price {n(price)} is VAT-inclusive, so whether it is over the maximum {n(mx)} "
                                         f"depends on the VAT basis of the maximum, which is not stated.", ev)
        return _res(rule, "pass", f"Unit price {n(price)} (VAT included) is within the maximum {n(mx)} on either VAT basis.", ev)
    if hit(over):
        return _res(rule, "fail", f"Unit price {n(price)} is {over:.2f}% above the maximum {n(mx)}.", ev)
    return _res(rule, "pass", f"Unit price {n(price)} is {over:+.2f}% vs the maximum {n(mx)}.", ev)


def advance_over(ctx: Ctx, rule: dict) -> RuleResult:
    mx = D(_p(rule).get("max_pct", 20))
    if not ctx.ok("advance_pct"):
        return _res(rule, "unknown", f"Advance payment not verified ({ctx.why('advance_pct')}).")
    adv = ctx.num("advance_pct")
    ev = ctx.quotes("advance_pct")
    if adv > mx:
        return _res(rule, "fail", f"Advance payment is {n(adv)}%, above the {n(mx)}% limit.", ev)
    return _res(rule, "pass", f"Advance payment is {n(adv)}% (limit {n(mx)}%).", ev)


def penalty_clause_missing(ctx: Ctx, rule: dict) -> RuleResult:
    if not ctx.ok("penalty_clause_present"):
        return _res(rule, "unknown", f"Could not confirm whether a penalty clause exists ({ctx.why('penalty_clause_present')}).")
    if ctx.val("penalty_clause_present") is False:
        return _res(rule, "fail", "There is no late-delivery penalty clause.",
                    [f"Clauses found in the document: {ctx.outline()}. None covers late delivery or penalties."])
    return _res(rule, "pass", "A late-delivery penalty clause is present.", ctx.quotes("penalty_clause_present"))


def tin_bin_missing(ctx: Ctx, rule: dict) -> RuleResult:
    t, b = ctx.facts["tin"], ctx.facts["bin"]
    missing = [name for name, f in (("TIN", t), ("BIN", b)) if f.status == "absent"]
    if missing:
        quote = (t.quote if t.status == "absent" else None) or (b.quote if b.status == "absent" else None)
        ev = [quote] if quote else ["No TIN/BIN number appears anywhere in the document."]
        return _res(rule, "fail", f"Supplier {' and '.join(missing)} not shown.", ev)
    if t.status == "ok" and b.status == "ok":
        return _res(rule, "pass", "Supplier TIN and BIN are both present.", ctx.quotes("tin", "bin"))
    return _res(rule, "unknown", f"TIN/BIN not verified ({ctx.why('tin', 'bin')}).")


def delivery_days(ctx: Ctx, rule: dict) -> RuleResult:
    p = _p(rule)
    gt = D(p["over_days_gt"]) if p.get("over_days_gt") is not None else None
    lte = D(p["over_days_lte"]) if p.get("over_days_lte") is not None else None
    if not ctx.ok("delivery_value", "delivery_unit"):
        return _res(rule, "unknown", f"Delivery time not verified ({ctx.why('delivery_value', 'delivery_unit')}).")
    v, unit = ctx.num("delivery_value"), ctx.val("delivery_unit")
    ev = ctx.quotes("delivery_value", "delivery_unit")
    if unit == "days":
        days = v
    elif unit == "weeks":
        days = v * 7
    else:
        return _res(rule, "unknown", f"Delivery is promised in {unit}, which cannot be converted to days exactly.", ev)
    said = f"{n(v)} {unit}" + (f" = {n(days)} days" if unit == "weeks" else "")
    if (gt is None or days > gt) and (lte is None or days <= lte):
        band = f"more than {n(gt)} days" + (f" and up to {n(lte)}" if lte is not None else "")
        return _res(rule, "fail", f"Delivery is promised in {said} ({band}).", ev)
    return _res(rule, "pass", f"Delivery is promised in {said}.", ev)


def quantity_deviation(ctx: Ctx, rule: dict) -> RuleResult:
    mx = D(_p(rule).get("max_pct", 5))
    if not ctx.cmp.get("matched"):
        return _res(rule, "unknown", f"Cannot compare the quantity: {ctx.cmp.get('reason')}.")
    if "qty_dev_pct" not in ctx.cmp:
        return _res(rule, "unknown", f"Quantity not verified ({ctx.why('quantity')}).")
    dev, req, got = D(ctx.cmp["qty_dev_pct"]), D(ctx.cmp["qty_requested"]), D(ctx.cmp["qty_quoted"])
    ev = ctx.quotes("quantity") + [f"purchase-request.csv: quantity requested {n(req)}"]
    if abs(dev) > mx:
        return _res(rule, "fail", f"Quoted quantity {n(got)} differs from the requested {n(req)} by {dev:+.2f}% (limit {n(mx)}%).", ev)
    return _res(rule, "pass", f"Quoted quantity {n(got)} vs requested {n(req)} ({dev:+.2f}%).", ev)


def payment_terms(ctx: Ctx, rule: dict) -> RuleResult:
    p = _p(rule)
    lo_ok, hi_ok = D(p.get("min_days", 30)), D(p.get("max_days", 60))
    if not ctx.ok("payment_days_min", "payment_days_max"):
        return _res(rule, "unknown", f"Payment period not verified ({ctx.why('payment_days_min', 'payment_days_max')}).")
    lo, hi = ctx.num("payment_days_min"), ctx.num("payment_days_max")
    ev = ctx.quotes("payment_days_min", "payment_days_max")
    if lo != hi:
        return _res(rule, "fail", f"Payment terms are unclear: a range of {n(lo)} to {n(hi)} days instead of a fixed period.", ev)
    if not (lo_ok <= lo <= hi_ok):
        return _res(rule, "fail", f"Payment is due {n(lo)} days after delivery, outside {n(lo_ok)} to {n(hi_ok)} days.", ev)
    return _res(rule, "pass", f"Payment is due {n(lo)} days after delivery (allowed {n(lo_ok)} to {n(hi_ok)}).", ev)


def vat_shown_separately(ctx: Ctx, rule: dict) -> RuleResult:
    rate = D(_p(rule).get("rate_pct", 15))
    if not ctx.ok("price_includes_vat"):
        return _res(rule, "unknown", f"VAT treatment not verified ({ctx.why('price_includes_vat')}).")
    if ctx.val("price_includes_vat") is True:
        return _res(rule, "fail", "VAT is included in the unit price instead of being shown separately.",
                    ctx.quotes("price_includes_vat"))
    if not ctx.ok("vat_rate_pct", "vat_amount"):
        return _res(rule, "unknown", f"VAT line not verified ({ctx.why('vat_rate_pct', 'vat_amount')}).")
    ev = ctx.quotes("vat_rate_pct")
    if ctx.num("vat_rate_pct") != rate:
        return _res(rule, "fail", f"VAT is shown at {n(ctx.num('vat_rate_pct'))}% instead of {n(rate)}%.", ev)
    return _res(rule, "pass", f"VAT is shown separately at {n(rate)}%.", ev)


def arithmetic(ctx: Ctx, rule: dict) -> RuleResult:
    tol = D(_p(rule).get("tolerance_bdt", 0.01))
    need = ("quantity", "unit_price", "line_amount", "price_includes_vat")
    if not ctx.ok(*need):
        return _res(rule, "unknown", f"Amounts not verified ({ctx.why(*need)}).")
    q, p, la = ctx.num("quantity"), ctx.num("unit_price"), ctx.num("line_amount")
    problems, missing, ev = [], [], ctx.quotes("quantity", "line_amount")
    if abs(q * p - la) > tol:
        problems.append(f"line amount {n(la)} is not quantity {n(q)} x unit price {n(p)} = {n(q * p)}")
    if ctx.val("price_includes_vat") is True:
        if ctx.ok("total"):
            ev += ctx.quotes("total")
            if abs(ctx.num("total") - la) > tol:
                problems.append(f"total {n(ctx.num('total'))} differs from the line amount {n(la)}")
        else:
            missing.append("total")
    else:
        for name in ("subtotal", "vat_rate_pct", "vat_amount", "total"):
            if not ctx.ok(name):
                missing.append(name)
        if not missing:
            sub, rt, vat, tot = ctx.num("subtotal"), ctx.num("vat_rate_pct"), ctx.num("vat_amount"), ctx.num("total")
            ev += ctx.quotes("subtotal", "vat_amount", "total")
            if abs(sub - la) > tol:
                problems.append(f"subtotal {n(sub)} differs from the line amount {n(la)}")
            if abs(sub * rt / 100 - vat) > tol:
                problems.append(f"VAT {n(vat)} is not {n(rt)}% of the subtotal {n(sub)} (= {n(sub * rt / 100)})")
            if abs(sub + vat - tot) > tol:
                problems.append(f"total {n(tot)} is not subtotal + VAT = {n(sub + vat)}")
    if problems:
        return _res(rule, "fail", "The numbers do not add up: " + "; ".join(problems) + ".", ev)
    if missing:
        return _res(rule, "unknown", f"Could not check all amounts ({ctx.why(*missing)}).")
    return _res(rule, "pass", "Line amount, subtotal, VAT and total all add up.", ev)


def validity_days(ctx: Ctx, rule: dict) -> RuleResult:
    mn = D(_p(rule).get("min_days", 30))
    if not ctx.ok("validity_days"):
        return _res(rule, "unknown", f"Validity period not verified ({ctx.why('validity_days')}).")
    v = ctx.num("validity_days")
    ev = ctx.quotes("validity_days")
    if v < mn:
        return _res(rule, "fail", f"The quotation is valid for only {n(v)} days (minimum {n(mn)}).", ev)
    return _res(rule, "pass", f"The quotation is valid for {n(v)} days (minimum {n(mn)}).", ev)


def penalty_strength(ctx: Ctx, rule: dict) -> RuleResult:
    p = _p(rule)
    mn = D(p.get("min_pct_per_week", 0.5))
    if not ctx.ok("penalty_clause_present"):
        return _res(rule, "unknown", f"Penalty clause not verified ({ctx.why('penalty_clause_present')}).")
    if ctx.val("penalty_clause_present") is False:
        return _res(rule, "pass", "No penalty clause to measure (reported by rule R3).")
    need = ("penalty_pct", "penalty_period", "penalty_base")
    if not ctx.ok(*need):
        return _res(rule, "unknown", f"Penalty details not verified ({ctx.why(*need)}).", ctx.quotes("penalty_clause_present"))
    ev = ctx.quotes("penalty_pct", "penalty_period", "penalty_base")
    if ctx.val("penalty_period") != "week":
        return _res(rule, "unknown", f"The penalty is set per {ctx.val('penalty_period')}, not per week, so it cannot be compared with the rule.", ev)
    if p.get("require_base_stated", True) and ctx.val("penalty_base") != "order_value":
        return _res(rule, "unknown", "The penalty percentage is not stated as a share of the order value, so it cannot be compared with the rule.", ev)
    pct = ctx.num("penalty_pct")
    if pct < mn:
        return _res(rule, "fail", f"Penalty is {n(pct)}% of order value per week, below the {n(mn)}% minimum.", ev)
    return _res(rule, "pass", f"Penalty is {n(pct)}% of order value per week (minimum {n(mn)}%).", ev)


CHECKS = {
    "price_over_max": price_over_max,
    "advance_over": advance_over,
    "penalty_clause_missing": penalty_clause_missing,
    "tin_bin_missing": tin_bin_missing,
    "delivery_days": delivery_days,
    "quantity_deviation": quantity_deviation,
    "payment_terms": payment_terms,
    "vat_shown_separately": vat_shown_separately,
    "arithmetic": arithmetic,
    "validity_days": validity_days,
    "penalty_strength": penalty_strength,
}


# --------------------------------------------------------------------------------- loading / running
def validate_rules(rules: list[dict]) -> None:
    seen = set()
    for r in rules:
        for k in ("id", "check", "severity"):
            if k not in r:
                raise ValueError(f"rules.yaml: a rule is missing '{k}': {r}")
        if r["check"] not in CHECKS:
            raise ValueError(f"rules.yaml: rule {r['id']} uses unknown check '{r['check']}'. Known: {sorted(CHECKS)}")
        if r["severity"] not in ("reject", "needs_person"):
            raise ValueError(f"rules.yaml: rule {r['id']} has severity '{r['severity']}' (use reject or needs_person)")
        if r["id"] in seen:
            raise ValueError(f"rules.yaml: duplicate rule id {r['id']}")
        seen.add(r["id"])


def load_rules(path: str | Path) -> tuple[list[dict], dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or []
    validate_rules(rules)
    return rules, data.get("settings") or {}


def run_rules(rules: list[dict], ctx: Ctx) -> list[RuleResult]:
    out = []
    for rule in rules:
        if rule.get("enabled", True) is False:
            continue
        try:
            out.append(CHECKS[rule["check"]](ctx, rule))
        except Exception as e:  # a bug or odd input must never crash the run or become a guess
            out.append(_res(rule, "unknown", f"This check could not run ({type(e).__name__}: {e})."))
    return out


def make_rules_node(rules: list[dict]):
    def check_rules_node(state: dict) -> dict:
        t0 = time.time()
        facts = {k: Fact(**v) for k, v in state["facts"].items()}
        ctx = Ctx(facts, state["comparison"], state["raw_text"])
        results = run_rules(rules, ctx)
        c = {s: sum(1 for r in results if r.status == s) for s in ("pass", "fail", "unknown")}
        msg = f"{len(results)} rules checked: {c['pass']} pass, {c['fail']} fail, {c['unknown']} could not be verified"
        return {"rule_results": [r.model_dump() for r in results],
                "trace": [{"step": "check_rules", "ok": True, "summary": msg, "ms": int((time.time() - t0) * 1000)}]}
    return check_rules_node
