from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .llm import make_llm
from .steps.match import load_purchase_request
from .steps.rules import load_rules

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class PipelineConfig:
    extractor: str  # "regex" (offline, deterministic) or "llm" (LLM + rule-based cross-check)
    rules: list[dict]
    settings: dict
    pr_lines: dict
    llm: object | None = None
    extras: dict = field(default_factory=dict)


def resolve_extractor(requested: str) -> str:
    if requested == "auto":
        return "llm" if os.getenv("GEMINI_API_KEY") else "regex"
    if requested not in ("llm", "regex"):
        raise ValueError(f"extractor must be auto, llm or regex (got {requested!r})")
    return requested


def load_config(extractor: str = "auto", rules_path: str | Path | None = None, pr_path: str | Path | None = None,
                cache_dir: str | Path | None = None, refresh: bool = False) -> PipelineConfig:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    mode = resolve_extractor(extractor)
    rules, settings = load_rules(rules_path or ROOT / "rules.yaml")
    pr_lines = load_purchase_request(pr_path or ROOT / "data" / "purchase-request.csv")
    cache = cache_dir or os.getenv("SUPPLIER_CHECK_CACHE_DIR") or ROOT / "cache" / "llm"
    llm = make_llm(cache, refresh=refresh) if mode == "llm" else None
    return PipelineConfig(extractor=mode, rules=rules, settings=settings, pr_lines=pr_lines, llm=llm)
