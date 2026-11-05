"""Step 1 - read the PDF into text. Fails loudly (never silently) on unreadable files."""
from __future__ import annotations

import time
from pathlib import Path

MIN_TEXT_CHARS = 40


def read_pdf_text(path: str | Path) -> str:
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return "\n".join(pages).strip()


def ingest_node(state: dict) -> dict:
    t0 = time.time()
    if state.get("raw_text") is not None:
        text = state["raw_text"]
    else:
        try:
            text = read_pdf_text(state.get("pdf_path"))
        except Exception as e:  # corrupt / encrypted / missing file
            return {
                "fatal_errors": [f"Could not open the PDF: {e}"],
                "trace": [{"step": "ingest", "ok": False, "summary": f"cannot read PDF: {e}"}],
            }
    if len(text) < MIN_TEXT_CHARS:
        msg = ("The PDF has no readable text layer (it looks like a scan or an image). "
               "OCR is not enabled, so a person must read it.")
        return {"fatal_errors": [msg], "trace": [{"step": "ingest", "ok": False, "summary": msg}]}
    return {
        "raw_text": text,
        "trace": [{"step": "ingest", "ok": True,
                   "summary": f"read {len(text)} characters of text", "ms": int((time.time() - t0) * 1000)}],
    }
