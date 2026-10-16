"""Process DoFE migration reports: download → extract → verify → tidy CSV.

Reads bill-tracker/migration_manifest.json, downloads each pending PDF, extracts
country/district approval rows, runs the math audit, writes per-document CSV under
output/migration/docs/ and the combined tracked panel to migration/panel.csv.

  python -m migration_parser process [--max-count N] [--force]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import requests
import urllib3

from .. import extract_doc, melt, verify
from ..agencies import INSTITUTIONAL, PREAPPROVAL
from ..model import DocMeta
from ..paths import (
    MIGRATION_DIR,
    MIGRATION_MANIFEST,
    MIGRATION_OUTPUT_DIR,
    MIGRATION_PANEL_COLUMNS,
    load_env,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0"}
PDFS_DIR = MIGRATION_OUTPUT_DIR / "pdfs"
DOCS_DIR = MIGRATION_OUTPUT_DIR / "docs"
MIGRATION_DATA_DIR = MIGRATION_DIR
PANEL_COLUMNS = MIGRATION_PANEL_COLUMNS

# Documents whose tables are extracted by the annex/agencies stages (not the
# live wide-table parser); skip them here so we never mislabel them "no_table".
OTHER_STAGE_SERIALS = {
    f[:3] for f in list(PREAPPROVAL) + list(INSTITUTIONAL)
}


def load_manifest() -> list[dict]:
    return json.loads(MIGRATION_MANIFEST.read_text())


def save_manifest(entries: list[dict]) -> None:
    MIGRATION_MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def content_id(url: str | None) -> str:
    if not url:
        return ""
    m = re.search(r"/content/(\d+)/", url)
    return m.group(1) if m else ""


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 1000:
        return True
    try:
        r = requests.get(url, headers=HEADERS, timeout=120, verify=False)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except requests.exceptions.RequestException as e:
        print(f"  [download error] {url}: {e}", file=sys.stderr)
        return False


def process_entry(entry: dict) -> tuple[list[dict], str]:
    """Download + extract one manifest entry. Returns (rows, status)."""
    pdf_url = entry.get("pdf_url")
    if not pdf_url:
        return [], "no_pdf"
    cid = content_id(entry.get("detail_url"))
    dest = PDFS_DIR / f"{entry['serial']:03d}_{cid or 'x'}.pdf"
    if not download(pdf_url, dest):
        return [], "failed"

    meta = DocMeta(
        doc_id=cid or str(entry["serial"]),
        filename=dest.name,
        source_url=pdf_url,
        title=entry.get("title", ""),
    )
    result = extract_doc(str(dest), meta)
    report = verify(result)
    if not result.wide_rows:
        return [], "no_table"

    rows = melt(result)
    verified = report.ok and not result.problems
    for row in rows:
        row["verified"] = verified
        row["source_url"] = pdf_url
    entry["period_bs"] = meta.period_bs
    entry["period_ad_start"] = meta.period_ad_start
    entry["period_ad_end"] = meta.period_ad_end
    entry["doc_type"] = meta.doc_type
    entry["checks"] = report.summary()
    entry["problems"] = result.problems
    entry["verified"] = verified

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(rows, DOCS_DIR / f"{entry['serial']:03d}_{cid or 'x'}.csv")
    return rows, "done" if verified else "unverified"


def _write_csv(rows: list[dict], path: Path) -> None:
    fields = [c for c in PANEL_COLUMNS if c in rows[0]] if rows else PANEL_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _load_all_docs() -> list[dict]:
    rows: list[dict] = []
    if not DOCS_DIR.exists():
        return rows
    for f in sorted(DOCS_DIR.glob("*.csv")):
        with open(f, newline="", encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    return rows


def rebuild_panel() -> int:
    """Rebuild migration/panel.csv from all per-doc CSVs (idempotent)."""
    panel = _load_all_docs()
    if panel:
        _write_csv(panel, MIGRATION_DATA_DIR / "panel.csv")
        print(f"\nWrote {len(panel)} rows to migration/panel.csv", file=sys.stderr)
    return len(panel)


def main(argv: list[str] | None = None) -> int:
    load_env()
    p = argparse.ArgumentParser(prog="migration process")
    p.add_argument("--max-count", type=int, default=None)
    p.add_argument("--force", action="store_true")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    MIGRATION_DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()

    done = 0
    for entry in manifest:
        if entry.get("status") == "skipped":
            continue
        if f"{entry['serial']:03d}" in OTHER_STAGE_SERIALS:
            continue
        if entry.get("status") in ("done", "unverified", "no_table") and not args.force:
            continue
        if args.max_count is not None and done >= args.max_count:
            break
        rows, status = process_entry(entry)
        entry["status"] = status
        entry["processed_at"] = time.strftime("%Y-%m-%d")
        done += 1
        n_c = sum(1 for r in rows if r["section"] == "country" and r["row_type"] == "detail")
        n_d = sum(1 for r in rows if r["section"] == "district" and r["row_type"] == "detail")
        print(f"[{status:11s}] #{entry['serial']:03d} {entry.get('title','')[:45]:45s} "
              f"country={n_c} district={n_d} {entry.get('checks','')}", file=sys.stderr)
        save_manifest(manifest)

    rebuild_panel()
    print(f"processed {done} docs this run", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
