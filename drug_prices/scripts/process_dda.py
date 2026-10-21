"""Process DDA drug price documents: download, OCR, Gemini, structured JSON.

Usage:
    python process_dda.py                    Process one pending entry
    python process_dda.py --max-count 5     Process up to 5 entries
    python process_dda.py --dry-run          Show what would be processed
"""

import json
import os
import re
import sys
import time
import urllib3
from pathlib import Path

import requests

from config import (
    DDA_COLUMN_REGIONS,
    DDA_MANIFEST,
    DDA_OUTPUT_DIR,
    GEMINI_API,
    GEMINI_MODEL,
    GEMINI_TEMPERATURE,
    HEADERS,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    TRANSLATIONS_DIR,
    load_env,
)
from dda_schema import DDA_SYSTEM_INSTRUCTION, build_dda_prompt, _output_token_budget
from ocr_dda import ocr_image
from render_dda import render_pdf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAX_RETRIES_GEMINI = 4


def load_manifest() -> list:
    if DDA_MANIFEST.exists():
        return json.loads(DDA_MANIFEST.read_text())
    return []


def save_manifest(entries: list):
    for i, e in enumerate(entries, 1):
        e["serial"] = f"{i}."
    DDA_MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def pick_pending(entries: list) -> int | None:
    for i, e in enumerate(entries):
        if e.get("status") != "pending":
            continue
        if not e.get("file_url"):
            continue
        return i
    return None


def download_file(url: str, dest: Path) -> bool:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False, stream=True
            )
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"  [retry] {url} ({e}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
    print(f"  [error] download failed: {url}: {last_err}", file=sys.stderr)
    return False


def _classify_gemini_error(err) -> str:
    msg = str(err).lower()
    if any(kw in msg for kw in ["rate limit", "high demand", "try again later"]):
        return "rpm"
    if any(kw in msg for kw in ["429", "403", "resource_exhausted", "quota"]):
        return "rpd"
    if "max_tokens" in msg or "truncat" in msg:
        return "truncated"
    return "other"


def call_gemini(ocr_text: str, api_key: str, budget: int | None = None) -> dict:
    if budget is None:
        budget = _output_token_budget(ocr_text)

    prompt = build_dda_prompt(ocr_text)
    payload = {
        "system_instruction": {"parts": [{"text": DDA_SYSTEM_INSTRUCTION}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": budget,
        },
    }

    resp = requests.post(
        f"{GEMINI_API}/{GEMINI_MODEL}:generateContent",
        headers={"Content-Type": "application/json"},
        params={"key": api_key},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    finish_reason = candidates[0].get("finishReason", "")
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    text = "".join(p.get("text", "") for p in parts)

    if finish_reason == "MAX_TOKENS":
        raise RuntimeError(f"TRUNCATED:{len(text)}:{budget}")

    return json.loads(text)


def ocr_entry(dest: Path, source_type: str) -> str:
    """OCR a downloaded file, returning combined text from all pages/images."""
    ocr_lines = []

    if source_type == "pdf":
        png_paths = render_pdf(dest, outdir=DDA_OUTPUT_DIR)
        print(f"  rendered {len(png_paths)} pages", file=sys.stderr)
        for png_path in png_paths:
            lines = ocr_image(png_path)
            ocr_lines.extend(lines)
            print(f"  OCR {png_path.name}: {len(lines)} lines", file=sys.stderr)
    else:
        # JPG/PNG — OCR directly
        lines = ocr_image(dest)
        ocr_lines.extend(lines)
        print(f"  OCR {dest.name}: {len(lines)} lines", file=sys.stderr)

    ocr_lines.sort(key=lambda r: (r["page"], r["y"], r["x"]))
    return "\n".join(l["text"] for l in ocr_lines)


def process_one(entries: list, index: int, api_key: str) -> bool:
    entry = entries[index]
    title = entry.get("title", "unknown")
    file_url = entry["file_url"]
    source_type = entry.get("source_type", "pdf")

    print(f"\n[process] {title[:60]}...", file=sys.stderr)

    # 1. Download
    # Use index as fallback for titles with non-ASCII chars
    stem = re.sub(r"[^\w]+", "_", title)[:50].strip("_").lower()
    if not stem or stem == "_":
        stem = f"entry_{index}"
    DDA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    ext = source_type if source_type in ("pdf", "jpg", "png") else "dat"
    dest = DDA_OUTPUT_DIR / f"{stem}.{ext}"

    if not download_file(file_url, dest):
        entries[index]["status"] = "failed"
        save_manifest(entries)
        return False
    print(f"  downloaded -> {dest}", file=sys.stderr)

    # 2. OCR
    ocr_text = ocr_entry(dest, source_type)
    if not ocr_text.strip():
        print("  [warn] no OCR text extracted", file=sys.stderr)
        entries[index]["status"] = "failed"
        save_manifest(entries)
        return False

    # Save raw OCR text
    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    ocr_path = TRANSLATIONS_DIR / f"dda-{stem}-ocr.txt"
    ocr_path.write_text(ocr_text)
    print(f"  OCR text -> {ocr_path} ({len(ocr_text)} chars)", file=sys.stderr)

    # 3. Gemini structured extraction (with retry)
    budget = _output_token_budget(ocr_text)
    result = None
    for attempt in range(MAX_RETRIES_GEMINI):
        try:
            result = call_gemini(ocr_text, api_key, budget=budget)
            break
        except RuntimeError as e:
            err_type = _classify_gemini_error(e)
            if err_type == "rpd":
                print("  [quota] daily limit reached, stopping", file=sys.stderr)
                return False
            if err_type == "truncated":
                parts = str(e).split(":")
                used = int(parts[1]) if len(parts) > 1 else budget
                budget = min(int(used * 1.5) + 2048, MAX_OUTPUT_TOKENS)
                print(f"  [truncated] growing budget to {budget}", file=sys.stderr)
                if budget >= MAX_OUTPUT_TOKENS:
                    print("  [error] budget exhausted", file=sys.stderr)
                    break
                time.sleep(2)
                continue
            if err_type == "rpm":
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"  [rate limit] waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [error] Gemini: {e}", file=sys.stderr)
            break
        except Exception as e:
            print(f"  [error] Gemini: {e}", file=sys.stderr)
            break

    if result is None:
        entries[index]["status"] = "failed"
        save_manifest(entries)
        return False

    # 4. Save outputs
    json_path = TRANSLATIONS_DIR / f"dda-{stem}.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"  structured JSON -> {json_path}", file=sys.stderr)

    # Update manifest
    entries[index]["status"] = "done"
    entries[index]["ocr_path"] = str(ocr_path)
    entries[index]["structured_path"] = str(json_path)
    entries[index]["drug_count"] = result.get("summary", {}).get("total_drugs", 0)
    save_manifest(entries)

    drug_count = result.get("summary", {}).get("total_drugs", "?")
    print(f"  done: {drug_count} drugs extracted", file=sys.stderr)
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Process DDA drug price documents")
    parser.add_argument("--max-count", type=int, default=1, help="Max entries to process")
    parser.add_argument("--dry-run", action="store_true", help="Show pending entries")
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get("GEMINI_API_KEY", "")

    entries = load_manifest()
    if not entries:
        print("[error] no manifest found, run scrape_dda.py first", file=sys.stderr)
        sys.exit(1)

    processed = 0
    while processed < args.max_count:
        idx = pick_pending(entries)
        if idx is None:
            print("[done] no more pending entries", file=sys.stderr)
            break

        if args.dry_run:
            e = entries[idx]
            print(f"  pending: {e['title'][:60]} -> {e.get('file_url', 'no url')[:80]}")
            entries[idx]["status"] = "skipped"
            continue

        if not api_key:
            print("[error] GEMINI_API_KEY not set", file=sys.stderr)
            sys.exit(1)

        ok = process_one(entries, idx, api_key)
        if ok:
            processed += 1

    print(f"\n[done] processed {processed} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
