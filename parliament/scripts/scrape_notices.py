import json
import re
import sys
import time
import urllib3
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    HEADERS,
    HR_BASE,
    HR_LIST_URL,
    MAX_RETRIES,
    MIN_BS_MONTH,
    MIN_BS_YEAR,
    NOTICES_MANIFEST,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    SCRAPE_DELAY,
    load_env,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = HR_BASE
LIST_URL = HR_LIST_URL
MANIFEST = NOTICES_MANIFEST


def load_manifest() -> list:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return []


def save_manifest(notices: list):
    for i, n in enumerate(notices, 1):
        n["serial"] = f"{i}."
    MANIFEST.write_text(json.dumps(notices, indent=2, ensure_ascii=False))
    print(f"[manifest] wrote {len(notices)} entries", file=sys.stderr)


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


def fetch_page(url: str) -> BeautifulSoup | None:
    resp = fetch_with_retry(url)
    if resp:
        return BeautifulSoup(resp.text, "lxml")
    return None


BS_DATE_RE = re.compile(r"(20\d{2})[-./]?(\d{1,2})?")


def is_old_parliament(title: str) -> bool:
    """True if title's BS/AD date predates the current (7th) HoR.

    Undated titles (e.g. session-call notices) are treated as current-era
    so they are never dropped or re-added as old noise.
    """
    m = BS_DATE_RE.search(title)
    if not m:
        return False
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else 1
    return (year, month) < (MIN_BS_YEAR, MIN_BS_MONTH)


def extract_notices(soup: BeautifulSoup) -> list[dict]:
    notices = []
    table = soup.select_one("table.table.table-bordered.table-striped.table-hover")
    if not table:
        return notices
    for row in table.select("tbody tr"):
        cells = row.select("td")
        if len(cells) < 3:
            continue
        link = cells[1].select_one("a")
        if not link or not link.get("href"):
            continue
        href = link["href"]
        if not href.startswith("http"):
            href = BASE + href
        notices.append({
            "serial": cells[0].get_text(strip=True),
            "title": link.get_text(strip=True) or "(no title)",
            "url": href,
            "pdf_url": None,
            "status": "pending",
            "scraped_at": time.strftime("%Y-%m-%d"),
        })
    return notices


def get_total_pages(soup: BeautifulSoup) -> int:
    pagination = soup.select_one("ul.pagination")
    if not pagination:
        return 1
    max_page = 1
    for a in pagination.select("a[href]"):
        m = re.search(r"page=(\d+)", a["href"])
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


def scrape_list_only():
    existing = load_manifest()
    existing_urls = {n["url"] for n in existing}
    new_notices = []
    page = 1
    while True:
        url = f"{LIST_URL}?get_by=all&n_type=parliament_notices&page={page}"
        print(f"[list] page {page}...", file=sys.stderr)
        soup = fetch_page(url)
        if not soup:
            break
        items = extract_notices(soup)
        if not items:
            break
        total_pages = get_total_pages(soup)
        seen_old = False
        kept = []
        for n in items:
            if is_old_parliament(n["title"]):
                seen_old = True
                break
            if n["url"] not in existing_urls:
                kept.append(n)
        new_notices.extend(kept)
        print(
            f"  -> {len(items)} notices ({len(new_notices)} new so far, "
            f"old_parliament={seen_old})",
            file=sys.stderr,
        )
        if seen_old:
            print(
                f"[done] stopped at page {page}: reached pre-7th-HoR notices "
                f"(BS < {MIN_BS_YEAR}-{MIN_BS_MONTH})",
                file=sys.stderr,
            )
            break
        if page >= total_pages:
            break
        page += 1
        time.sleep(SCRAPE_DELAY)
    if new_notices:
        existing[0:0] = new_notices
        save_manifest(existing)
    print(f"[done] {len(new_notices)} new, {len(existing)} total", file=sys.stderr)


def backfill_pdfs():
    notices = load_manifest()
    changed = 0
    for i, n in enumerate(notices):
        if n.get("pdf_url") or not n.get("url"):
            continue
        print(f"  [detail] {n['title'][:60]}...", file=sys.stderr)
        pdf_url = fetch_detail_pdf_url(n["url"])
        if pdf_url:
            notices[i]["pdf_url"] = pdf_url
            print(f"    -> {pdf_url}", file=sys.stderr)
        else:
            print(f"    -> none", file=sys.stderr)
            notices[i]["status"] = "no_pdf"
        changed += 1
        time.sleep(SCRAPE_DELAY)
        if changed % 20 == 0:
            save_manifest(notices)
    if changed:
        save_manifest(notices)
    print(f"[done] backfilled {changed} PDFs", file=sys.stderr)


def fetch_detail_pdf_url(detail_url: str) -> str | None:
    soup = fetch_page(detail_url)
    if not soup:
        return None
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/uploads/attachments/" in href:
            if not href.startswith("http"):
                href = BASE + href
            return href
    for a in soup.select("a[href$='.pdf']"):
        href = a["href"]
        if not href.startswith("http"):
            href = BASE + href
        return href
    return None


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--backfill":
        backfill_pdfs()
    else:
        scrape_list_only()