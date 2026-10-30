"""
Test: Gemini structured JSON extraction from a single already-OCR'd notice.

Sends the Devanagari OCR text to Gemini with a JSON schema prompt.
Returns both the full translation + structured metadata in one response.

Usage:
    export GEMINI_API_KEY='key'
    python scripts/test_structured_prompt.py datasets/translations/Notice_2083-03-31-ocr.txt

Compares output with existing freeform translation at datasets/translations/Notice_2083-03-31.txt
"""

import argparse
import json
import os
import sys
from pathlib import Path

from kagaj_core import llm as core_llm

from config import (
    GEMINI_MODEL,
    GEMINI_SYSTEM_INSTRUCTION,
    GEMINI_TEMPERATURE,
    load_env,
)
from schema import NOTICE_PROMPT, build_schema

_SCHEMA_DESC = build_schema()
STRUCTURED_PROMPT = NOTICE_PROMPT


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def call_gemini_structured(ocr_text: str, api_key: str) -> dict:
    prompt = STRUCTURED_PROMPT.format(schema=_SCHEMA_DESC, ocr_text=ocr_text)
    return core_llm.call_structured(
        prompt,
        api_key=api_key,
        model=GEMINI_MODEL,
        system_instruction=GEMINI_SYSTEM_INSTRUCTION,
        temperature=GEMINI_TEMPERATURE,
        max_output_tokens=16384,
    )


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Test structured Gemini extraction on one OCR'd notice")
    parser.add_argument("ocr_file", help="Path to the Devanagari OCR .txt file")
    parser.add_argument("--output", "-o", help="Save structured JSON result to this path")
    parser.add_argument("--compare", help="Path to existing English translation .txt for comparison")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    ocr_path = Path(args.ocr_file)
    if not ocr_path.exists():
        print(f"Error: {ocr_path} not found", file=sys.stderr)
        sys.exit(1)

    ocr_text = read_file(ocr_path)
    print(f"[input] {ocr_path.name} — {len(ocr_text)} chars", file=sys.stderr)

    print(f"[gemini] sending to {GEMINI_MODEL}...", file=sys.stderr)
    result = call_gemini_structured(ocr_text, api_key)
    print(f"[gemini] response received", file=sys.stderr)

    translation = result.get("full_translation_en", "")
    print(f"[result] full_translation_en: {len(translation)} chars", file=sys.stderr)
    print(f"[result] sections: {len(result.get('sections', []))}", file=sys.stderr)
    print(f"[result] speakers: {len(result.get('all_speakers_mentioned', []))}", file=sys.stderr)
    print(f"[result] agenda_tags: {result.get('agenda_tags', [])}", file=sys.stderr)

    if args.compare:
        existing = read_file(Path(args.compare))
        existing_len = len(existing)
        overlap = len(set(translation.split()) & set(existing.split()))
        total = max(len(set(translation.split())), len(set(existing.split())))
        sim = overlap / total if total > 0 else 0
        print(f"[compare] existing translation: {existing_len} chars", file=sys.stderr)
        print(f"[compare] word overlap ratio: {sim:.2f}", file=sys.stderr)

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"[output] saved to {out_path}", file=sys.stderr)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
