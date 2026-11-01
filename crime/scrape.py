"""Discover and download CID monthly crime bulletins."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .schema import fiscal_year, month_key, parse_issue_title

BASE = "https://cid.nepalpolice.gov.np"
LISTING = BASE + "/publication/4/?page={page}"
PAGES = range(1, 7)

MANIFEST = Path(__file__).resolve().parent / "manifests" / "bulletins.json"
PDF_DIR = Path(__file__).resolve().parent.parent / "output" / "crime" / "pdfs"


def _session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "kagaj-crime/0.1"
    session.verify = False
    return session


def discover(session: requests.Session | None = None) -> list[dict]:
    session = session or _session()
    entries: dict[str, dict] = {}
    for page in PAGES:
        url = LISTING.format(page=page)
        try:
            response = session.get(url, timeout=60)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"listing page {page} failed: {exc}")
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if ".pdf" not in href.lower() or "/media/" not in href:
                continue
            full = urljoin(BASE, href)
            title = " ".join(anchor.get_text(" ", strip=True).split())
            if full not in entries or (title and not entries[full]["title"]):
                year, month, issue = parse_issue_title(title)
                entries[full] = {
                    "url": full,
                    "title": title,
                    "bs_year": year,
                    "bs_month": month,
                    "issue_no": issue,
                    "month_key": month_key(year, month) if year and month else None,
                    "fy": fiscal_year(year, month) if year and month else None,
                }
    rows = list(entries.values())
    rows.sort(key=lambda r: (r["bs_year"] or 0, r["bs_month"] or 0, r["url"]))
    return rows


def write_manifest(rows: list[dict], path: Path = MANIFEST) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def download(row: dict, pdf_dir: Path = PDF_DIR, force: bool = False) -> Path:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    stem = row.get("month_key") or hashlib.sha1(row["url"].encode()).hexdigest()[:12]
    path = pdf_dir / f"{stem}.pdf"
    if path.exists() and not force and path.stat().st_size > 10_000:
        return path
    session = _session()
    for attempt in range(3):
        try:
            with session.get(row["url"], timeout=120, stream=True) as response:
                response.raise_for_status()
                tmp = path.with_suffix(".part")
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        handle.write(chunk)
                tmp.replace(path)
                return path
        except requests.RequestException as exc:
            if attempt == 2:
                raise
            print(f"retry {attempt + 1} for {row['url']}: {exc}")
            time.sleep(2 * (attempt + 1))
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
