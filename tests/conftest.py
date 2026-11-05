import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from supplier_check.config import load_config
from supplier_check.graph import build_graph, run_document
from supplier_check.steps.ingest import read_pdf_text

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted((ROOT / "data" / "samples").glob("supplier-pack-*.pdf"))
TRUTH = json.loads((ROOT / "data" / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def app():
    return build_graph(load_config("regex"))


@pytest.fixture(scope="session")
def texts():
    return {p.stem: read_pdf_text(p) for p in SAMPLES}


def check_text(app, text, doc_id="mutant"):
    return run_document(app, doc_id=doc_id, text=text)


def mutate(text: str, *pairs):
    """Replace strings, failing loudly if a replacement does not match exactly once (no silent no-ops)."""
    for old, new in pairs:
        assert text.count(old) == 1, f"mutation target not found exactly once: {old!r}"
        text = text.replace(old, new)
    return text


def reprice(text: str, qty, price):
    """Rewrite the line item, subtotal, VAT and total consistently for a new quantity and price."""
    q, p = Decimal(str(qty)), Decimal(str(price))
    line = (q * p).quantize(Decimal("0.01"))
    vat = (line * Decimal("0.15")).quantize(Decimal("0.01"))
    total = line + vat
    f = lambda d: f"{d:,.2f}"  # noqa: E731
    text = re.sub(r"^(?P<h>[A-Z]\s+.+?\s+)\d[\d,]*(?:\.\d+)?(?P<u>\s+[A-Za-z]+\s+)\d[\d,]*\.\d{2}\s+\d[\d,]*\.\d{2}$",
                  lambda m: f"{m['h']}{int(q):,}{m['u']}{f(p)} {f(line)}", text, count=1, flags=re.M)
    text = re.sub(r"^Subtotal .*$", f"Subtotal {f(line)}", text, flags=re.M)
    text = re.sub(r"^VAT 15% .*$", f"VAT 15% {f(vat)}", text, flags=re.M)
    text = re.sub(r"^Total .*$", f"Total {f(total)}", text, flags=re.M)
    return text
