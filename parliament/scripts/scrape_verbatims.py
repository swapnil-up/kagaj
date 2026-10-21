"""Scrape the National Assembly verbatim catalogue into a manifest.

Source: NA API  https://na.parliament.gov.np/api/v1/verbatims?limit=500
Returns all National Assembly meeting verbatims (currently 431) in one
page, each with a published_at date and a direct attachment_url (PDF).

Output (verbatims.json) mirrors the notices.json shape, keyed by stable
API id so re-runs never duplicate entries. Only verbatims from the 19th
NA session onward (current-parliament era) are kept; older sessions go to
verbatims-archive.json and are never re-added:

    [
      {
        "serial": "1.",
        "id": 2984,
        "title": "Complete Proceedings of the Twenty-First Session ... (Meeting no. 34)",
        "title_np": "एक्काइसौँ अधिवेशन कार्यवाहीको सम्पूर्ण विवरण ...",
        "published_at": "2026-08-07",
        "attachment_url": "https://na.parliament.gov.np/uploads/attachments/fio7sqeo9rolgtoy.pdf",
        "status": "pending",
        "scraped_at": "2026-08-10"
      }
    ]

Usage:
    .venv/bin/python scripts/scrape_verbatims.py
"""

import json
import re
import sys
import time
import urllib3
from pathlib import Path

import requests

from config import (
    HEADERS,
    MAX_RETRIES,
    MIN_NA_SESSION,
    NA_ATTACH_BASE,
    NA_LIST_URL,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    VERBATIMS_MANIFEST,
    load_env,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIST_URL = NA_LIST_URL
ATTACH_BASE = NA_ATTACH_BASE
MANIFEST = VERBATIMS_MANIFEST

# Verbatims from the 19th NA session onward (BS 2082-10 ~ Dec 2025) are kept
# in the manifest — the current-parliament era (7th HoR first session began
# 2026-04-02 / BS 2082-12, with session 19 a little before that). Older
# sessions live in verbatims-archive.json and are never re-added.
MIN_SESSION = MIN_NA_SESSION

# Devanagari session ordinals as they appear in title_np (e.g. "एक्काइसौँ अधिवेशन").
SESSION_NUMBERS = {
    "पहिलो": 1, "पहिलौँ": 1, "दोस्रो": 2, "तेस्रो": 3, "चौथो": 4,
    "पाँचौ": 5, "पाँचौं": 5, "पाचौं": 5,
    "छैठौं": 6, "छैटाैं": 6,
    "सातौँ": 7, "आठाैँ": 8, "नवौँ": 9, "नवाैँ": 9, "दशाैँ": 10,
    "एघारौँ": 11, "बाह्रौँ": 12, "बाह्रौं": 12, "तेह्रौँ": 13,
    "चौधौँ": 14, "पन्ध्रौँ": 15, "सोह्रौँ": 16, "सत्रौँ": 17,
    "सत्रौं": 17, "अठारौं": 18, "उन्नाइसौँ": 19, "उन्नाइसौ": 19,
    "बिसौँ": 20, "बिसौं": 20, "एक्काइसौँ": 21, "बाइसौँ": 22,
}

SESSION_PREFIX_RE = re.compile(r"^[\s\-_]*([\u0900-\u097f]{3,})\s*अधिवेशन")


def load_manifest() -> list:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return []


def save_manifest(verbatims: list):
    for i, v in enumerate(verbatims, 1):
        v["serial"] = f"{i}."
    MANIFEST.write_text(json.dumps(verbatims, indent=2, ensure_ascii=False))
    print(f"[manifest] wrote {len(verbatims)} entries", file=sys.stderr)


def fetch_with_retry(url: str) -> requests.Response | None:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"[retry] {url} ({e}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
    print(f"[error] {url}: {last_err}", file=sys.stderr)
    return None


def session_number(item: dict) -> int:
    """Parse the NA session number from title_np's leading ordinal."""
    m = SESSION_PREFIX_RE.match(item.get("title_np") or "")
    if not m:
        return 0
    return SESSION_NUMBERS.get(m.group(1), 0)


def is_old_session(item: dict) -> bool:
    """True if the verbatim predates the current-parliament era."""
    return session_number(item) < MIN_SESSION


def extract_verbatims(payload: dict) -> list[dict]:
    items = []
    for v in payload.get("data", []):
        attach = v.get("attachment_url") or {}
        attachment_name = attach.get("attachmentName")
        locales = {t.get("locale"): t.get("title") for t in v.get("verbatim_translations", [])}
        items.append({
            "id": v.get("id"),
            "title": v.get("title") or "",
            "title_np": locales.get("np", ""),
            "published_at": v.get("published_at", ""),
            "attachment_url": f"{ATTACH_BASE}/{attachment_name}" if attachment_name else None,
            "status": "pending" if attachment_name else "no_pdf",
            "scraped_at": time.strftime("%Y-%m-%d"),
        })
    return items


def scrape():
    existing = load_manifest()
    existing_ids = {v.get("id") for v in existing}
    print(f"[fetch] {LIST_URL}?limit=500...", file=sys.stderr)
    resp = fetch_with_retry(f"{LIST_URL}?limit=500")
    if not resp:
        sys.exit(1)
    data = resp.json().get("data", {})
    items = extract_verbatims(data)
    new = [v for v in items if v["id"] not in existing_ids and not is_old_session(v)]
    old_skipped = sum(1 for v in items if is_old_session(v))
    existing.extend(new)
    total = data.get("total")
    print(f"  -> {len(items)} fetched, {len(new)} new, {old_skipped} old-session skipped "
          f"(API total={total}, manifest={len(existing)})", file=sys.stderr)
    if new:
        save_manifest(existing)
    print(f"[done] {len(new)} new, {len(existing)} total", file=sys.stderr)


if __name__ == "__main__":
    scrape()