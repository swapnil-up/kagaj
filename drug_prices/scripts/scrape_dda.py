"""Scrape DDA MRP (drug price) category for PDFs and price notices.

Two modes:
  python scrape_dda.py              Scrape MRP category page + price notices
  python scrape_dda.py --backfill   Fetch detail pages for entries missing file_url
"""

import json
import re
import sys
import time
import urllib3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    DDA_BASE,
    DDA_MANIFEST,
    DDA_MRP_PAGE,
    HEADERS,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    SCRAPE_DELAY,
    load_env,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def load_manifest() -> list:
    if DDA_MANIFEST.exists():
        return json.loads(DDA_MANIFEST.read_text())
    return []


def save_manifest(entries: list):
    for i, e in enumerate(entries, 1):
        e["serial"] = f"{i}."
    DDA_MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    print(f"[manifest] wrote {len(entries)} entries", file=sys.stderr)


def fetch_with_retry(url: str) -> requests.Response | None:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False
            )
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2**attempt)
                print(f"[retry] {url} ({e}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
    print(f"[error] {url}: {last_err}", file=sys.stderr)
    return None


def fetch_page(url: str) -> BeautifulSoup | None:
    resp = fetch_with_retry(url)
    if resp:
        return BeautifulSoup(resp.text, "lxml")
    return None


def extract_mrp_entries(soup: BeautifulSoup) -> list[dict]:
    """Extract entries from the MRP category page table."""
    entries = []
    for row in soup.select("table.table tbody tr, table tbody tr"):
        cells = row.select("td")
        if len(cells) < 4:
            continue
        # cells: serial | title | date | file_type | actions
        title_cell = cells[1] if len(cells) > 1 else cells[0]
        date_cell = cells[2] if len(cells) > 2 else None
        file_cell = cells[3] if len(cells) > 3 else None

        title = title_cell.get_text(strip=True) or "(no title)"
        date_str = date_cell.get_text(strip=True) if date_cell else ""

        # Find PDF link in the row
        pdf_url = None
        content_url = None
        for a in row.select("a[href]"):
            href = a["href"].strip()
            if href.endswith(".pdf") or "pdf_upload" in href:
                if not href.startswith("http"):
                    href = DDA_BASE + href
                pdf_url = href
            elif "/content/" in href:
                if not href.startswith("http"):
                    href = DDA_BASE + href
                content_url = href

        if not pdf_url and not content_url:
            continue

        url = (content_url or pdf_url).strip()
        entries.append({
            "title": title,
            "date_str": date_str,
            "url": url,
            "source_type": "pdf",
            "file_url": pdf_url,
            "status": "pending",
            "scraped_at": time.strftime("%Y-%m-%d"),
        })
    return entries


def extract_price_notices(soup: BeautifulSoup) -> list[dict]:
    """Extract price-related notices from the main notices page.

    Looks for entries with 'मूल्य' (price) or 'दर' (rate) in the title,
    which may have JPG images instead of PDFs.
    """
    entries = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if not text or not href:
            continue
        # Match price-related entries (मूल्य = price, but NOT दर्ता = registration)
        if not re.search(r"मूल्य|MRP|price|Price", text, re.IGNORECASE):
            continue
        if "/content/" not in href:
            continue
        if not href.startswith("http"):
            href = DDA_BASE + href
        entries.append({
            "title": text,
            "date_str": "",
            "url": href,
            "source_type": "unknown",  # determined at detail page
            "file_url": None,
            "status": "pending",
            "scraped_at": time.strftime("%Y-%m-%d"),
        })
    return entries


def scrape_mrp_page() -> list[dict]:
    """Scrape the DDA MRP category page."""
    print(f"[scrape] fetching {DDA_MRP_PAGE}", file=sys.stderr)
    soup = fetch_page(DDA_MRP_PAGE)
    if not soup:
        print("[error] could not fetch MRP page", file=sys.stderr)
        return []

    entries = extract_mrp_entries(soup)
    print(f"[scrape] found {len(entries)} MRP entries", file=sys.stderr)
    return entries


def scrape_notices_page() -> list[dict]:
    """Scrape the main DDA notices page for price-related entries."""
    notices_url = f"{DDA_BASE}/"
    print(f"[scrape] fetching notices from {notices_url}", file=sys.stderr)
    soup = fetch_page(notices_url)
    if not soup:
        print("[error] could not fetch notices page", file=sys.stderr)
        return []

    entries = extract_price_notices(soup)
    print(f"[scrape] found {len(entries)} price-related notices", file=sys.stderr)
    return entries


def scrape_list():
    existing = load_manifest()
    existing_urls = {e["url"] for e in existing}

    new_entries = []

    # Scrape MRP category page
    mrp_entries = scrape_mrp_page()
    for e in mrp_entries:
        if e["url"] not in existing_urls:
            new_entries.append(e)
            existing_urls.add(e["url"])

    # Scrape main notices for price entries
    time.sleep(SCRAPE_DELAY)
    notice_entries = scrape_notices_page()
    for e in notice_entries:
        if e["url"] not in existing_urls:
            new_entries.append(e)
            existing_urls.add(e["url"])

    if new_entries:
        existing.extend(new_entries)
        save_manifest(existing)

    print(
        f"[done] {len(new_entries)} new, {len(existing)} total",
        file=sys.stderr,
    )


def backfill_detail_pages():
    """Fetch detail pages for entries missing file_url to find PDF/image URLs."""
    entries = load_manifest()
    changed = 0
    for i, e in enumerate(entries):
        if e.get("file_url") or not e.get("url"):
            continue
        print(
            f"  [detail] {e['title'][:60]}...",
            file=sys.stderr,
        )
        file_url, source_type = fetch_detail_file_url(e["url"])
        if file_url:
            entries[i]["file_url"] = file_url
            entries[i]["source_type"] = source_type
            print(f"    -> {source_type}: {file_url}", file=sys.stderr)
        else:
            print("    -> no file found", file=sys.stderr)
            entries[i]["status"] = "no_file"
        changed += 1
        time.sleep(SCRAPE_DELAY)
        if changed % 20 == 0:
            save_manifest(entries)
    if changed:
        save_manifest(entries)
    print(f"[done] backfilled {changed} detail pages", file=sys.stderr)


def fetch_detail_file_url(detail_url: str) -> tuple[str | None, str]:
    """Fetch a detail page and extract PDF or image URL.

    Returns (url, source_type) where source_type is 'pdf', 'jpg', or 'png'.
    """
    soup = fetch_page(detail_url)
    if not soup:
        return None, "unknown"

    # Look for PDF links
    for a in soup.select("a[href]"):
        href = a["href"]
        if href.endswith(".pdf") or "pdf_upload" in href:
            if not href.startswith("http"):
                href = DDA_BASE + href
            return href, "pdf"

    # Look for image links (JPG/PNG in media albums)
    skip_patterns = ["topbg_", "newlogo", "Emblem_of_Nepal", "Nepal-flag", ".370x245"]
    for a in soup.select("a[href]"):
        href = a["href"]
        if any(skip in href for skip in skip_patterns):
            continue
        if any(
            ext in href.lower()
            for ext in [".jpg", ".jpeg", ".png", "pdf_upload"]
        ):
            if not href.startswith("http"):
                href = DDA_BASE + href
            ext = "jpg" if ".jpg" in href.lower() or ".jpeg" in href.lower() else "png"
            return href, ext

    # Check for embedded images in the page content
    # Skip common background/theme images
    skip_patterns = ["topbg_", "newlogo", "Emblem_of_Nepal", "Nepal-flag", ".370x245"]
    for img in soup.select("img[src]"):
        src = img["src"]
        if any(skip in src for skip in skip_patterns):
            continue
        if "pdf_upload" in src or any(
            ext in src.lower() for ext in [".jpg", ".jpeg", ".png"]
        ):
            if not src.startswith("http"):
                src = DDA_BASE + src
            ext = "jpg" if ".jpg" in src.lower() or ".jpeg" in src.lower() else "png"
            return src, ext

    return None, "unknown"


if __name__ == "__main__":
    load_env()
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        backfill_detail_pages()
    else:
        scrape_list()
