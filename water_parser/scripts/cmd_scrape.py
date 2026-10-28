"""``water_parser scrape`` — build the KUKL schedule manifest.

Fetches the public water-distribution-schedule page, collects every PDF / XLSX /
DOC attachment, and records branch + month parsed from the file name. The
manifest is tracked (``datasets/water/manifest.json``) and re-runnable: entries are keyed
on URL, so previously-processed rows keep their status.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
import urllib3

from .. import paths

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _already(manifest: dict, url: str) -> dict | None:
    for e in manifest.get("entries", []):
        if e.get("url") == url:
            return e
    return None


def run(args) -> int:
    resp = requests.get(
        paths.KUKL_SCHEDULE_URL,
        timeout=60,
        verify=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; water-parser/0.1)"},
    )
    resp.raise_for_status()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "lxml")
    entries: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/storage/download/" not in href:
            continue
        filename = urlparse(href).path.rsplit("/", 1)[-1]
        parsed = paths.parse_filename(filename)
        if not parsed or not filename.lower().endswith(paths.SUPPORTED_SUFFIXES):
            continue
        if href in seen:
            continue
        seen.add(href)
        entries.append({
            **parsed,
            "kind": paths.kind_for(filename),
            "filename": filename,
            "url": href,
            "status": "pending",
        })

    if not entries:
        print("[scrape] no schedule attachments found — page structure changed?")
        return 1

    existing = {}
    if paths.MANIFEST.exists():
        old = json.loads(paths.MANIFEST.read_text())
        existing = {e["url"]: e for e in old.get("entries", [])}

    merged = []
    for e in entries:
        prev = existing.get(e["url"])
        if prev and prev.get("status") in ("done", "unsupported"):
            e.update({k: prev[k] for k in
                      ("status", "text_path", "structured_path", "downloaded_path")
                      if k in prev})
        merged.append(e)

    paths.WATER_DIR.mkdir(parents=True, exist_ok=True)
    paths.MANIFEST.write_text(json.dumps({
        "source": paths.KUKL_SCHEDULE_URL,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": merged,
    }, ensure_ascii=False, indent=2) + "\n")

    months: dict[str, int] = {}
    branches: set[str] = set()
    for e in merged:
        months[e["month_key"]] = months.get(e["month_key"], 0) + 1
        branches.add(e["branch"])
    print(f"[scrape] {len(merged)} attachments → {paths.MANIFEST}")
    print(f"[scrape] {len(branches)} branches, {len(months)} months")
    for mk in sorted(months, reverse=True)[:8]:
        print(f"          {mk}: {months[mk]}")
    return 0
