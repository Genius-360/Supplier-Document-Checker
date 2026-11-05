from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

APPROVE = "Approve"
REJECT = "Reject"
NEEDS_PERSON = "Needs a person to check"
VERDICTS = (APPROVE, REJECT, NEEDS_PERSON)


class Fact(BaseModel):
    """One value read from a document, with the exact text that supports it.

    status:
      ok       - value is usable (it was verified against the document text)
      absent   - the document was checked and the thing is really not there
      unknown  - could not be read or verified; rules must NOT treat it as a value
    """

    value: Any = None
    quote: str | None = None
    status: Literal["ok", "absent", "unknown"] = "ok"
    reason: str | None = None
    source: str = "regex"  # "regex" | "llm"


class Extraction(BaseModel):
    extractor: str
    facts: dict[str, Fact] = Field(default_factory=dict)
    error: str | None = None


class RuleResult(BaseModel):
    rule_id: str
    check: str
    severity: Literal["reject", "needs_person"]
    status: Literal["pass", "fail", "unknown"]
    message: str
    text: str = ""
    evidence: list[str] = Field(default_factory=list)
