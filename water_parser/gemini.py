"""Structured-JSON client for water schedules.

Thin wrapper over :mod:`kagaj_core.llm`, kept so the water pipeline has one
place for its prompt, model, and retry policy.
"""

from __future__ import annotations

from kagaj_core.llm import GeminiError, call_structured as _call_structured
from kagaj_core.llm import output_token_budget

MODEL = "gemini-2.5-flash-lite"
TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 65536
MAX_RETRIES = 4
RETRY_DELAY = 5

SYSTEM_INSTRUCTION = (
    "You extract structured data from Nepali water-distribution schedules. "
    "The input may be a spreadsheet dump or noisy OCR. Never invent data."
)

__all__ = ["GeminiError", "call_structured", "output_token_budget"]


def call_structured(prompt: str, api_key: str | None = None) -> dict:
    """Send a prompt expecting a JSON object back; return the parsed dict."""
    return _call_structured(
        prompt,
        api_key=api_key,
        model=MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_retries=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
    )
