# Cheat-sheet for the 30-minute call ("change one thing live")

Know where each change lives. Run `pytest -q` after each change (about 5 seconds), and `python -m supplier_check` to show the effect.

| They ask for | Edit | Time |
|---|---|---|
| "Make the advance limit 15%" / any number | `rules.yaml`: the rule's `params` | 30 s |
| "Treat X as Needs a person instead of Reject" | `rules.yaml`: change `severity` | 30 s |
| "Turn off the TIN rule" | `rules.yaml`: `enabled: false` on R4 | 30 s |
| "Penalty must be at least 1%" | `rules.yaml`: P1 `min_pct_per_week: 1` | 30 s |
| "Reject if delivery is over 40 days" | `rules.yaml`: R5 `over_days_gt: 40`, N4 `over_days_lte: 40` | 1 min |
| "Add a new rule" (new kind of check) | 1) function in `steps/rules.py`, 2) add to `CHECKS`, 3) entry in `rules.yaml` | 5 min |
| "Also read a new field" (e.g. incoterm) | add a row to `FIELD_SPECS` in `fields.py`; the LLM prompt and verification pick it up; add a regex in `steps/regex_extractor.py` for offline mode | 5 min |
| "Run just one file" | `python -m supplier_check --file data/samples/supplier-pack-09.pdf` | 10 s |
| "Show the human pause" | add `--interactive` | 10 s |
| "Where are the results?" | `results/regex/` and `results/llm/`: `summary.md` plus one JSON audit record per document | 10 s |

**New-check skeleton** (`steps/rules.py`):
```python
def max_total(ctx, rule):                       # e.g. "reject if total over a limit"
    if not ctx.ok("total"):
        return _res(rule, "unknown", f"Total not verified ({ctx.why('total')}).")
    limit = D(_p(rule)["limit"])
    if ctx.num("total") > limit:
        return _res(rule, "fail", f"Total {n(ctx.num('total'))} is over {n(limit)}.", ctx.quotes("total"))
    return _res(rule, "pass", "Total is within the limit.", ctx.quotes("total"))
# register:  CHECKS["max_total"] = max_total
# yaml:      - {id: N8, check: max_total, severity: needs_person, params: {limit: 7000000}, text: "..."}
```

**Questions to expect, short answers**
* *Why not one agent?* Fixed steps are predictable and auditable; a free agent can skip a check.
* *Where can the LLM hurt you?* It cannot reach a verdict: every value is verified against the text and cross-checked,
  and failures become "Needs a person". Tests: `tests/test_llm_path.py`.
* *Why is 10/10 not enough?* Built on the same files; hence the boundary and mutation tests.
* *What if the layout changes?* Offline parser says unknown -> person. LLM extractor handles layout; verification still applies.
