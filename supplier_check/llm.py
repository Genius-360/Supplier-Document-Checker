"""LLM access: Gemini client, on-disk cache, and the exception used when no model is reachable."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"  # override with GEMINI_MODEL in .env


class LLMUnavailable(RuntimeError):
    """No API key and no cached answer for this exact request."""


class GeminiLLM:
    name = "gemini"
    RETRIES = 5  # waits 2, 4, 8, 16 seconds between attempts

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from google import genai

        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self.fallback = os.getenv("GEMINI_FALLBACK_MODEL") or None  # optional backup if the main model is overloaded
        self.last_model = self.model
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])

    def _call(self, model: str, system: str, user: str) -> str:
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system, temperature=0, response_mime_type="application/json"
        )
        last = None
        for attempt in range(self.RETRIES):
            try:
                resp = self.client.models.generate_content(model=model, contents=user, config=cfg)
                self.last_model = model
                return resp.text or ""
            except Exception as e:  # noqa: BLE001
                last = e
                code = getattr(e, "code", None)
                busy = code in (429, 500, 502, 503, 504) or "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e)
                if not busy:
                    raise  # a real error (bad key, bad request...): do not hide it behind retries
                if attempt < self.RETRIES - 1:
                    time.sleep(2 ** (attempt + 1))
        raise LLMUnavailable(f"Gemini model '{model}' kept failing: {last}")

    def complete_json(self, system: str, user: str) -> str:
        models = [self.model] + ([self.fallback] if self.fallback and self.fallback != self.model else [])
        last = None
        for m in models:
            try:
                return self._call(m, system, user)
            except LLMUnavailable as e:  # overloaded: try the backup model if one is configured
                last = e
        raise last


class CachedLLM:
    """Remembers every answer on disk, keyed by the exact prompt.

    This makes reruns free, deterministic and offline (commit the cache folder),
    and lets someone without an API key reproduce the LLM results.
    """

    def __init__(self, inner, cache_dir: str | Path, refresh: bool = False):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.refresh = refresh
        self.hits = 0
        self.calls = 0

    def _path(self, system: str, user: str) -> Path:
        key = hashlib.sha256((system + "\n\x00\n" + user).encode("utf-8")).hexdigest()[:24]
        return self.dir / f"{key}.json"

    def complete_json(self, system: str, user: str) -> str:
        p = self._path(system, user)
        if p.exists() and not self.refresh:
            self.hits += 1
            return json.loads(p.read_text(encoding="utf-8"))["response"]
        if self.inner is None:
            raise LLMUnavailable("no GEMINI_API_KEY set and this request is not in the cache")
        self.calls += 1
        out = self.inner.complete_json(system, user)
        try:
            json.loads(out)  # only cache answers that are valid JSON
            p.write_text(json.dumps({"model": getattr(self.inner, "last_model", getattr(self.inner, "model", "?")), "response": out},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        except ValueError:
            pass
        return out


def make_llm(cache_dir: str | Path, refresh: bool = False):
    """Real Gemini if GEMINI_API_KEY is set, otherwise cache-only."""
    inner = GeminiLLM() if os.getenv("GEMINI_API_KEY") else None
    return CachedLLM(inner, cache_dir, refresh=refresh)
