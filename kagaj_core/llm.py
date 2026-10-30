"""Dependency-light Gemini client for structured JSON extraction.

The client speaks the raw REST API (no ``google-genai`` SDK), retries transient
failures, classifies quota errors, and can grow the output-token budget when a
JSON response is cut off by ``MAX_TOKENS``. ``requests`` is imported lazily so
importing :mod:`kagaj_core` stays cheap.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_EMBED_MODEL = "gemini-embedding-001"
DEFAULT_EMBED_DIMENSIONS = 768
DEFAULT_API = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_OUTPUT_TOKENS = 65536
DEFAULT_MAX_RETRIES = 4
DEFAULT_RETRY_DELAY = 5.0
DEFAULT_TIMEOUT = 300.0
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
TRUNCATION_GROWTH = 1.5


class GeminiError(RuntimeError):
    """Base error for Gemini requests, carrying a machine-readable kind."""

    kind = "other"

    def __init__(self, message: str, kind: str | None = None):
        super().__init__(message)
        if kind is not None:
            self.kind = kind


class QuotaError(GeminiError):
    """Gemini rejected the request for rate/quota reasons."""

    kind = "quota"


class TruncatedError(GeminiError):
    """The response was cut off before the JSON object completed."""

    kind = "truncated"


class TransientError(GeminiError):
    """A retryable network or upstream error persisted after all retries."""

    kind = "transient"


def classify_error(message: str) -> str:
    """Classify a Gemini error string as ``rpm``, ``rpd``, or ``other``."""
    lowered = message.lower()
    if any(p in lowered for p in ("rate limit", "high demand", "try again later")):
        return "rpm"
    if any(p in lowered for p in ("429", "403", "resource_exhausted", "quota")):
        return "rpd"
    return "other"


def output_token_budget(text: str, *, floor: int = 8192,
                        cap: int = DEFAULT_MAX_OUTPUT_TOKENS) -> int:
    """Choose an initial output budget from the input size."""
    return max(floor, min(len(text) // 2, cap))


def extract_json_text(payload: dict) -> str:
    """Pull the text of the first candidate out of a Gemini response."""
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError(f"no candidates: {json.dumps(payload)[:300]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise GeminiError("empty content from Gemini")
    return text


@dataclass
class GeminiClient:
    """Configuration for one Gemini model plus a ``structured`` helper."""

    model: str = DEFAULT_MODEL
    api: str = DEFAULT_API
    temperature: float = DEFAULT_TEMPERATURE
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    timeout: float = DEFAULT_TIMEOUT
    retry_on_quota: bool = True
    session: Any | None = None
    sleep: Callable[[float], None] = field(default=time.sleep)
    api_key: str | None = None

    def structured(self, prompt: str, *, system_instruction: str | None = None,
                   api_key: str | None = None, budget: int | None = None,
                   grow_on_truncation: bool = True) -> dict:
        """Send *prompt* expecting a JSON object; return the parsed result."""
        key = api_key or self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiError(
                "GEMINI_API_KEY not set (add .env at the repo root)")

        budget = budget or self.max_output_tokens
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": self.temperature,
                "maxOutputTokens": budget,
            },
        }
        if system_instruction:
            body["system_instruction"] = {
                "parts": [{"text": system_instruction}]
            }

        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            body["generationConfig"]["maxOutputTokens"] = budget
            response = self._post(key, body)
            if response is None:
                last_err = TransientError("network error")
                self.sleep(self.retry_delay * attempt)
                continue

            status = getattr(response, "status_code", 0)
            if status in TRANSIENT_STATUS:
                text = getattr(response, "text", "")[:500]
                kind = classify_error(text)
                if status == 429 and kind in ("rpm", "rpd") and not self.retry_on_quota:
                    raise QuotaError(f"{kind.upper()}: {text}", kind=kind)
                last_err = TransientError(f"HTTP {status}: {text}")
                self.sleep(self.retry_delay * attempt)
                continue

            body_json = _response_json(response)
            if not getattr(response, "ok", False):
                message = (body_json.get("error", {}).get("message")
                           or getattr(response, "text", "")[:500])
                kind = classify_error(message)
                if kind in ("rpm", "rpd"):
                    raise QuotaError(f"{kind.upper()}: {message}", kind=kind)
                raise GeminiError(f"Gemini API error: {message}", kind=kind)

            candidate = _first_candidate(body_json)
            finish_reason = candidate.get("finishReason", "")
            text = _candidate_text(candidate)
            try:
                return json.loads(text)
            except json.JSONDecodeError as error:
                if finish_reason == "MAX_TOKENS" and grow_on_truncation:
                    used = (_usage_tokens(body_json) or budget)
                    grown = min(int(used * TRUNCATION_GROWTH) + 2048,
                                self.max_output_tokens)
                    if grown > budget:
                        budget = grown
                        continue
                if finish_reason == "MAX_TOKENS":
                    raise TruncatedError(
                        f"response truncated at {budget} tokens: {error}")
                raise GeminiError(
                    f"Gemini returned invalid JSON ({error}): {text[:300]}")

        raise TransientError(f"exhausted retries: {last_err}")

    def generate_text(self, prompt: str, *,
                      system_instruction: str | None = None,
                      api_key: str | None = None,
                      temperature: float | None = None,
                      max_output_tokens: int | None = None,
                      max_retries: int | None = None) -> str:
        """Send *prompt* and return the first candidate's text."""
        key = api_key or self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiError(
                "GEMINI_API_KEY not set (add .env at the repo root)")
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": (self.temperature if temperature is None
                                else temperature),
            },
        }
        if max_output_tokens is not None:
            body["generationConfig"]["maxOutputTokens"] = max_output_tokens
        if system_instruction:
            body["system_instruction"] = {
                "parts": [{"text": system_instruction}]
            }

        attempts = max_retries or self.max_retries
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            response = self._post(key, body)
            if response is None:
                last_err = TransientError("network error")
                self.sleep(self.retry_delay * attempt)
                continue

            status = getattr(response, "status_code", 0)
            payload = _response_json(response)
            if status in TRANSIENT_STATUS:
                text = getattr(response, "text", "")[:500]
                kind = classify_error(text)
                if status == 429 and kind in ("rpm", "rpd") \
                        and not self.retry_on_quota:
                    raise QuotaError(f"{kind.upper()}: {text}", kind=kind)
                last_err = TransientError(f"HTTP {status}: {text}")
                self.sleep(self.retry_delay * attempt)
                continue

            if not getattr(response, "ok", False):
                message = (payload.get("error", {}).get("message")
                           or getattr(response, "text", "")[:500])
                kind = classify_error(message)
                if kind in ("rpm", "rpd"):
                    raise QuotaError(f"{kind.upper()}: {message}", kind=kind)
                raise GeminiError(f"Gemini API error: {message}", kind=kind)

            return _candidate_text(_first_candidate(payload))

        raise TransientError(f"exhausted retries: {last_err}")

    def embed(self, text: str, *, model: str | None = None,
              api_key: str | None = None,
              output_dimensionality: int = DEFAULT_EMBED_DIMENSIONS
              ) -> list[float]:
        """Embed one string, returning the vector values."""
        key = api_key or self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise GeminiError(
                "GEMINI_API_KEY not set (add .env at the repo root)")
        model = model or DEFAULT_EMBED_MODEL
        body = {
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
            "outputDimensionality": output_dimensionality,
        }
        response = self._post(key, body,
                              url=f"{self.api}/{model}:embedContent")
        if response is None:
            raise TransientError("network error")

        status = getattr(response, "status_code", 0)
        payload = _response_json(response)
        if not getattr(response, "ok", False):
            message = (payload.get("error", {}).get("message")
                       or getattr(response, "text", "")[:300])
            kind = classify_error(message)
            if status == 429 and kind not in ("rpm", "rpd"):
                kind = "rpd"
            if kind in ("rpm", "rpd"):
                raise QuotaError(f"{kind.upper()}: {message}", kind=kind)
            raise GeminiError(f"Embedding API error: {message}")

        values = (payload.get("embedding") or {}).get("values") or []
        if not values:
            raise GeminiError("Gemini returned no embedding values")
        return values

    def embed_many(self, texts: list[str], *, model: str | None = None,
                   api_key: str | None = None,
                   output_dimensionality: int = DEFAULT_EMBED_DIMENSIONS,
                   pause_every: int = 5, pause: float = 0.3
                   ) -> list[list[float]]:
        """Embed strings one at a time, pausing every *pause_every* calls."""
        results = []
        for index, text in enumerate(texts):
            results.append(self.embed(
                text, model=model, api_key=api_key,
                output_dimensionality=output_dimensionality))
            if pause_every and index > 0 and index % pause_every == 0:
                self.sleep(pause)
        return results

    def _post(self, api_key: str, body: dict, *, url: str | None = None):
        try:
            import requests
        except ImportError as error:  # pragma: no cover - requests is optional
            raise GeminiError(
                "requests is required for Gemini calls; install the billtracker extra"
            ) from error
        target = url or f"{self.api}/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        try:
            poster = self.session.post if self.session is not None else requests.post
            return poster(target, headers=headers, json=body, timeout=self.timeout)
        except requests.RequestException:
            return None


def call_structured(prompt: str, api_key: str | None = None, *,
                    model: str = DEFAULT_MODEL,
                    system_instruction: str | None = None,
                    temperature: float = DEFAULT_TEMPERATURE,
                    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
                    max_retries: int = DEFAULT_MAX_RETRIES,
                    retry_delay: float = DEFAULT_RETRY_DELAY,
                    retry_on_quota: bool = True,
                    timeout: float = DEFAULT_TIMEOUT,
                    budget: int | None = None) -> dict:
    """Convenience wrapper for one structured call."""
    client = GeminiClient(
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        max_retries=max_retries,
        retry_delay=retry_delay,
        retry_on_quota=retry_on_quota,
        timeout=timeout,
    )
    return client.structured(prompt, api_key=api_key,
                             system_instruction=system_instruction,
                             budget=budget)


def generate_text(prompt: str, api_key: str | None = None, *,
                  model: str = DEFAULT_MODEL,
                  system_instruction: str | None = None,
                  temperature: float = DEFAULT_TEMPERATURE,
                  max_output_tokens: int | None = None,
                  max_retries: int = DEFAULT_MAX_RETRIES,
                  retry_delay: float = DEFAULT_RETRY_DELAY,
                  retry_on_quota: bool = True,
                  timeout: float = DEFAULT_TIMEOUT) -> str:
    """Convenience wrapper for one plain-text generation call."""
    client = GeminiClient(
        model=model, temperature=temperature, max_output_tokens=max_output_tokens,
        max_retries=max_retries, retry_delay=retry_delay,
        retry_on_quota=retry_on_quota, timeout=timeout)
    return client.generate_text(
        prompt, api_key=api_key, system_instruction=system_instruction)


def embed(text: str, api_key: str | None = None, *,
          model: str = DEFAULT_EMBED_MODEL,
          output_dimensionality: int = DEFAULT_EMBED_DIMENSIONS,
          timeout: float = DEFAULT_TIMEOUT) -> list[float]:
    """Convenience wrapper for one embedding call."""
    client = GeminiClient(model=model, timeout=timeout)
    return client.embed(text, api_key=api_key,
                        output_dimensionality=output_dimensionality)


def embed_many(texts: list[str], api_key: str | None = None, *,
               model: str = DEFAULT_EMBED_MODEL,
               output_dimensionality: int = DEFAULT_EMBED_DIMENSIONS,
               pause_every: int = 5, pause: float = 0.3,
               timeout: float = DEFAULT_TIMEOUT) -> list[list[float]]:
    """Convenience wrapper for embedding a list of strings."""
    client = GeminiClient(model=model, timeout=timeout)
    return client.embed_many(
        texts, api_key=api_key, output_dimensionality=output_dimensionality,
        pause_every=pause_every, pause=pause)


def _response_json(response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {}


def _first_candidate(payload: dict) -> dict:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no candidates")
    return candidates[0]


def _candidate_text(candidate: dict) -> str:
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise GeminiError("Gemini returned empty content")
    return text


def _usage_tokens(payload: dict) -> int | None:
    usage = payload.get("usageMetadata") or {}
    value = usage.get("candidatesTokenCount")
    return int(value) if value else None
