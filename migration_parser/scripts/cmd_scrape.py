"""Scrape DoFE labour-migration report listings into a manifest.

Modes:
  python -m migration_parser scrape              enumerate categories, resolve PDF URLs
  python -m migration_parser scrape --list-only  enumerate listings only (fast)

Output: bill-tracker/migration_manifest.json
"""

from __future__ import annotations

import json
import re
import sys
import time

import requests
import urllib3
from bs4 import BeautifulSoup

from ..paths import (
    DOFE_BASE,
    DOFE_MIGRATION_CATEGORIES,
    DOFE_PDF_BARE_RE,
    DOFE_PDF_JS_RE,
    MIGRATION_MANIFEST,
    load_env,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
SCRAPE_DELAY = 0.8
MAX_PAGES = 15


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=40, verify=False)
        if r.status_code != 200:
            return None
        return r.text
    except requests.exceptions.RequestException as e:
        print(f"[error] {url}: {e}", file=sys.stderr)
        return None


def parse_grid(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    grid = soup.select_one("div.category-1-grid")
    if not grid:
        return []
    out = []
    for card in grid.select(".grid__card"):
        links = sorted({a.get("href", "").strip()
                        for a in card.select('a[href*="/content/"]')
                        if a.get("href", "").strip()})
        if not links:
            continue
        detail = links[0]
        if not detail.startswith("http"):
            detail = DOFE_BASE + detail
        title_el = card.select_one("h3,h2,h4,.card__title")
        date_els = card.select("[class*=date], time")
        out.append({
            "detail_url": detail,
            "title": title_el.get_text(strip=True) if title_el else "",
            "date_np": date_els[-1].get_text(strip=True) if date_els else "",
            "pdf_url": None,
        })
    return out


def parse_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for row in soup.select("table tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue
        title = cells[1].get_text(" ", strip=True)
        date_np = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""
        pdf_url = detail_url = None
        for a in row.select("a[href]"):
            href = a["href"].strip()
            if not href or href == "#":
                continue
            abs_url = href if href.startswith("http") else DOFE_BASE + href
            if href.endswith(".pdf") or "pdf_upload" in href:
                pdf_url = abs_url
            elif "/content/" in href:
                detail_url = abs_url
        if title or detail_url or pdf_url:
            out.append({"detail_url": detail_url, "title": title,
                        "date_np": date_np, "pdf_url": pdf_url})
    return out


def enumerate_category(name: str) -> list[dict]:
    entries, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        url = f"{DOFE_BASE}/category/{name}/" + (f"?page={page}" if page > 1 else "")
        html = fetch(url)
        if not html:
            break
        batch = parse_grid(html) or parse_table(html)
        new = 0
        for e in batch:
            key = e.get("detail_url") or e.get("pdf_url") or e.get("title")
            if key in seen:
                continue
            seen.add(key)
            entries.append(e)
            new += 1
        if new == 0:
            break
        time.sleep(SCRAPE_DELAY)
    print(f"[{name}] {len(entries)} entries", file=sys.stderr)
    return entries


def resolve_pdf(detail_url: str) -> str | None:
    html = fetch(detail_url)
    if not html:
        return None
    m = re.search(DOFE_PDF_JS_RE, html) or re.search(DOFE_PDF_BARE_RE, html)
    return m.group(1) if m else None


def load_manifest() -> list[dict]:
    if MIGRATION_MANIFEST.exists():
        return json.loads(MIGRATION_MANIFEST.read_text())
    return []


def save_manifest(entries: list[dict]) -> None:
    for i, e in enumerate(entries, 1):
        e["serial"] = i
    MIGRATION_MANIFEST.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False))
    print(f"[manifest] wrote {len(entries)} entries", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_env()
    list_only = "--list-only" in argv
    existing = load_manifest()
    by_key = {(e.get("detail_url") or e.get("pdf_url") or e.get("title")): e
              for e in existing}
    manifest = list(existing)

    for cat in DOFE_MIGRATION_CATEGORIES:
        for e in enumerate_category(cat):
            key = e.get("detail_url") or e.get("pdf_url") or e.get("title")
            if key in by_key:
                continue
            e["category"] = cat
            e["status"] = "pending"
            e["scraped_at"] = time.strftime("%Y-%m-%d")
            manifest.append(e)
            by_key[key] = e

    if not list_only:
        for e in manifest:
            if e.get("pdf_url") or not e.get("detail_url"):
                continue
            pdf = resolve_pdf(e["detail_url"])
            e["pdf_url"] = pdf
            if not pdf:
                e["status"] = "no_pdf"
            time.sleep(SCRAPE_DELAY)

    save_manifest(manifest)
    with_pdf = sum(1 for e in manifest if e.get("pdf_url"))
    print(f"[done] {len(manifest)} total, {with_pdf} with PDF", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
