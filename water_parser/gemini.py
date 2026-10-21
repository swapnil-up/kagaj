"""Thin Gemini client for structured JSON extraction.

Mirrors the call shape used by ``parliament/scripts/process_notice.py``:
raw REST, ``response_mime_type=application/json``, low temperature, retry on
transient errors. Kept dependency-free (requests only) so the water pipeline
does not pull in the google-genai SDK.
"""

from __future__ import annotations

import json
import os
import time

import requests

MODEL = "gemini-2.5-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models"
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 65536
MAX_RETRIES = 4
RETRY_DELAY = 5

SYSTEM_INSTRUCTION = (
    "You extract structured data from Nepali water-distribution schedules. "
    "The input may be a spreadsheet dump or noisy OCR. Never invent data."
)


class GeminiError(RuntimeError):
    pass


def _extract_json_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeminiError(f"no candidates: {json.dumps(payload)[:300]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        raise GeminiError("empty content from Gemini")
    return text


def call_structured(prompt: str, api_key: str | None = None) -> dict:
    """Send a prompt expecting a JSON object back; return the parsed dict."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY not set (add .env at the repo root)")

    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": TEMPERATURE,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{API}/{MODEL}:generateContent",
                headers={"Content-Type": "application/json"},
                params={"key": key},
                json=body,
                timeout=300,
            )
        except requests.RequestException as err:  # transient network
            last_err = err
            time.sleep(RETRY_DELAY * attempt)
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = GeminiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            time.sleep(RETRY_DELAY * attempt)
            continue
        if not resp.ok:
            raise GeminiError(f"HTTP {resp.status_code}: {resp.text[:400]}")

        text = _extract_json_text(resp.json())
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise GeminiError(f"response was not valid JSON: {err}: {text[:300]}")

    raise GeminiError(f"exhausted retries: {last_err}")
