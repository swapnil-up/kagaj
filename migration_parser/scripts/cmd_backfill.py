"""Archive.org backfill — extract older DoFE reports into tidy rows.

Family (a) only for now: monthly country-wise final-approval reports
(``historical.extract_monthly``). Give it one or more local PDFs (or a
directory) and it writes a JSON bundle of extracted rows + a validation
summary under ``output/migration/backfill/``. Merging into ``panel.csv`` (with a
new ``source_kind`` column) is a later step.

    python -m migration_parser backfill --extract <pdf-or-dir> [...]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
import urllib3

from ..historical import extract_monthly, melt
from ..model import DocMeta
from ..paths import MIGRATION_ARCHIVE_MANIFEST, MIGRATION_OUTPUT_DIR, REPO_ROOT
from ..periods import BS_MONTHS_EN, BS_MONTHS_NP, _norm_digits
from . import cmd_process as process

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
HEADERS = {"User-Agent": "Mozilla/5.0"}

BACKFILL_DIR = MIGRATION_OUTPUT_DIR / "backfill"
ARCHIVE_INVENTORY = MIGRATION_OUTPUT_DIR / "archive_org.json"
ARCHIVE_PDFS = MIGRATION_OUTPUT_DIR / "archive_pdfs"
ARCHIVE_MANIFEST = MIGRATION_ARCHIVE_MANIFEST

MONTH_LABEL = {
    1: "Baishakh", 2: "Jestha", 3: "Asar", 4: "Shrawan", 5: "Bhadra",
    6: "Ashwin", 7: "Kartik", 8: "Mangsir", 9: "Poush", 10: "Magh",
    11: "Falgun", 12: "Chaitra",
}

# filenames that name a month but are a different product/family
_EXCLUDE = (
    "sastha", "ujuri", "sushasan", "susashan", "sushan", "sushashan", "form",
    "purba", "district", "2050", "fy_wise", "final data", "quarter", "yearly",
    "annual", "बाषिर्क", "वार्षिक", "अर्धवार्षिक", "blocked", "manpower",
    "jitco", "lic", "notice", "visa", "salary", "contract", "training", "list",
)

# frequent romanisation slips in DoFE filenames
_EN_EXTRA = {
    "shreawan": 4, "sharwan": 4, "bhandra": 5, "aswin": 6, "magha": 10,
    "karthik": 7, "mangshir": 8, "poosh": 9, "baishak": 1, "jesth": 2,
}
_TIMESTAMP_SUFFIX = re.compile(r"_\d{8,}(?:\.\w+)?$")
# must look like a monthly approvals/progress report
_INCLUDE = (
    "monthly", "final-app", "final approval", "final report", "report of",
    "report_", "_report", "महिनाको", "महिना", "progress", "प्रगति",
)


_EN_MONTHS = {**BS_MONTHS_EN, **_EN_EXTRA}


def _month_of(norm: str) -> int | None:
    for m, num in BS_MONTHS_NP.items():
        if m in norm:
            return num
    # Not ``\b``: month names are commonly glued to the year in these filenames
    # (``2075shrawan``, ``ashad2075``), where ``\b`` fails between letter/digit.
    # Require instead that the month is not flanked by other letters.
    for m, num in _EN_MONTHS.items():
        if re.search(rf"(?<![a-z]){m}(?![a-z])", norm):
            return num
    return None


def _is_bare_month(norm: str) -> bool:
    """True when the filename *starts* with a month name (e.g. ``ashoj.pdf``).

    These carry no year token, so the year is only recoverable from the printed
    report header after fetch (see ``extract_one``).
    """
    return any(re.match(rf"{m}\b", norm) for m in _EN_MONTHS)


def _monthly_period(name: str) -> tuple[int | None, int] | None:
    """Parse ``(bs_year_or_None, month_number)`` from a report filename.

    Accepts Devanagari (``२०६९_कार्तिक_महिनाको...``) and romanised
    (``final-app-Kartik-2067.pdf``) month names. A filename qualifies when a
    month name is present **and** any of:

    * a BS year token is present (e.g. ``2075Shrawan.pdf``, ``Ashad2075.pdf``),
      so the report keyword is *not* required; or
    * a report keyword is present (``_INCLUDE``); or
    * the name is a **bare month** (``ashoj.pdf``) — ``year=None``; the year is
      read from the printed header at extraction time.

    ``_EXCLUDE`` still vetoes unrelated products that name a month.
    """
    stem = _TIMESTAMP_SUFFIX.sub("", unquote(name))
    low = stem.lower()
    if any(x in low for x in _EXCLUDE):
        return None
    norm = _norm_digits(low)
    month = _month_of(norm)
    if month is None:
        return None
    ym = re.search(r"(20\d\d)", norm)
    year = int(ym.group(1)) if ym else None
    if (year is None and not any(x in low for x in _INCLUDE)
            and not _is_bare_month(norm)):
        return None
    return year, month


def resolve_candidates() -> list[dict]:
    """Select monthly country-wise family-(a) PDFs from the Wayback inventory."""
    inv = json.loads(ARCHIVE_INVENTORY.read_text())
    best: dict[tuple[int | None, int], dict] = {}
    for host in ("dofe.gov.np", "feo.gov.np"):
        for ts, url, status, mime in inv.get(host, {}).get("pdfs", []):
            if str(status) != "200" or "pdf" not in str(mime).lower():
                continue
            fname = unquote(urlparse(url).path).split("/")[-1]
            period = _monthly_period(fname)
            if not period:
                continue
            year, month = period
            label = MONTH_LABEL[month]
            entry = {
                "title": fname,
                "source_url": url,
                "wayback_url": f"https://web.archive.org/web/{ts}id_/{url}",
                # Bare-month captures have no year in the name; the printed
                # header is read at extraction time (`extract_one`).
                "period_bs": f"{year} {label}" if year else f"unknown {label}",
                "status": "pending",
                "source_pdf_sha256": None,
                "pdf_bytes": None,
            }
            prev = best.get(period)
            # Prefer the version whose name says it is a final/monthly report.
            if prev is None or _prefer(fname, prev["title"]):
                best[period] = entry
    # Year-unknown keys sort after year-known ones (None is not orderable).
    order = sorted(best, key=lambda k: (k[0] is not None, k[0] or 0, k[1]))
    entries = [best[k] for k in order]
    for i, e in enumerate(entries, 1):
        e["serial"] = i
    return entries


def _prefer(a: str, b: str) -> bool:
    def score(s: str) -> int:
        s = s.lower()
        return sum(k in s for k in ("final", "monthly", "report"))
    return score(a) > score(b)


def _sha256(path: Path) -> str:
    return process.sha256_file(path)


def fetch_manifest(limit: int | None = None) -> int:
    ARCHIVE_PDFS.mkdir(parents=True, exist_ok=True)
    entries = json.loads(ARCHIVE_MANIFEST.read_text())
    done = 0
    for e in entries:
        if e["status"] not in ("pending", "failed") or e.get("source_pdf_sha256"):
            continue
        # Reuse a cache file carried over from an earlier resolve (serials can
        # change when the heuristic picks up new candidates).
        lp = e.get("local_path")
        if lp:
            p = REPO_ROOT / lp
            if p.exists() and p.stat().st_size > 1000:
                e["source_pdf_sha256"] = _sha256(p)
                e["pdf_bytes"] = p.stat().st_size
                e["status"] = "fetched"
                done += 1
                continue
        dest = ARCHIVE_PDFS / f"{e['serial']:03d}_{e['period_bs'].replace(' ', '_')}.pdf"
        if dest.exists() and dest.stat().st_size > 1000:
            e["source_pdf_sha256"] = _sha256(dest)
            e["pdf_bytes"] = dest.stat().st_size
            e["status"] = "fetched"
            e["local_path"] = str(dest.relative_to(REPO_ROOT))
            done += 1
            continue
        try:
            time.sleep(1.0)
            r = requests.get(e["wayback_url"], headers=HEADERS, timeout=180,
                             verify=False)
            r.raise_for_status()
            if b"%PDF" not in r.content[:1024]:
                e["status"] = "no_pdf"
                print(f"  [no_pdf] #{e['serial']} {e['title']}", file=sys.stderr)
                continue
            dest.write_bytes(r.content)
        except requests.exceptions.RequestException as ex:
            e["status"] = "failed"
            print(f"  [failed] #{e['serial']} {e['title']}: {ex}", file=sys.stderr)
            continue
        e["source_pdf_sha256"] = _sha256(dest)
        e["pdf_bytes"] = dest.stat().st_size
        e["status"] = "fetched"
        e["local_path"] = str(dest.relative_to(REPO_ROOT))
        done += 1
        print(f"  [ok] #{e['serial']:03d} {e['period_bs']} "
              f"({e['pdf_bytes'] / 1024:.0f} KB)", file=sys.stderr)
        if limit and done >= limit:
            break
    ARCHIVE_MANIFEST.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    return done


def _pdfs(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(p.glob("*.pdf")))
        elif p.exists():
            out.append(p)
        else:
            print(f"  [skip] not found: {p}", file=sys.stderr)
    return out


def _period_from_filename(name: str) -> str:
    """Recover ``"<year> <Month>"`` from a ``NNN_<year>_<Month>.pdf`` cache name."""
    m = re.search(r"(20\d\d)_([A-Za-z]+)", name)
    if not m:
        return ""
    return f"{m.group(1)} {m.group(2)}"


def extract_one(path: Path) -> dict:
    meta = DocMeta(doc_id=process.sha256_file(path)[:16], filename=path.name,
                   source_url="")
    doc = extract_monthly(str(path), meta=meta)
    # The cache filename ("NNN_<year>_<Month>.pdf") is the authoritative catalog
    # month; the printed header can mislabel the scope block. Keep the header
    # read too so a bad Wayback capture (content != filename) is auditable.
    header_period = meta.period_bs
    meta.period_bs = _period_from_filename(path.name) or meta.period_bs
    meta.doc_type = "single_month"
    return {
        "file": path.name,
        "doc_id": meta.doc_id,
        "period_bs": meta.period_bs,
        "header_period_bs": header_period,
        "doc_type": meta.doc_type,
        "layout": doc.layout,
        "verified": doc.verified,
        "scope_labels": doc.scope_labels,
        "countries": len({r.country for r in doc.rows}),
        "rows": len(doc.rows),
        "totals": {k: list(v) for k, v in doc.totals.items()},
        "problems": doc.problems,
        "warnings": doc.warnings,
        "data": melt(doc),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration backfill")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true",
                   help="print resolved candidates from the Wayback inventory")
    g.add_argument("--resolve", action="store_true",
                   help="write the tracked archive manifest from the inventory")
    g.add_argument("--fetch", action="store_true",
                   help="download pending manifest PDFs (offline cache)")
    g.add_argument("--extract", nargs="+", metavar="PATH",
                   help="PDF(s) or directory to extract")
    p.add_argument("--out", default=None, help="extract output JSON path")
    p.add_argument("--limit", type=int, default=None, help="max docs to fetch")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    if args.list:
        for e in resolve_candidates():
            print(f"#{e['serial']:03d} {e['period_bs']:16s} {e['title']}")
        return 0
    if args.resolve:
        entries = resolve_candidates()
        if ARCHIVE_MANIFEST.exists():
            old = {e["period_bs"]: e
                   for e in json.loads(ARCHIVE_MANIFEST.read_text())}
            carried = 0
            for e in entries:
                o = old.get(e["period_bs"])
                if not o or not o.get("source_pdf_sha256"):
                    continue
                lp = o.get("local_path")
                p = REPO_ROOT / lp if lp else None
                if p and p.exists() and _sha256(p) == o["source_pdf_sha256"]:
                    e["status"] = o["status"]
                    e["source_pdf_sha256"] = o["source_pdf_sha256"]
                    e["pdf_bytes"] = o["pdf_bytes"]
                    e["local_path"] = o["local_path"]
                    carried += 1
            print(f"carried over {carried} fetched capture(s)", file=sys.stderr)
        ARCHIVE_MANIFEST.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {ARCHIVE_MANIFEST} ({len(entries)} candidates)")
        return 0
    if args.fetch:
        n = fetch_manifest(limit=args.limit)
        print(f"fetched {n} PDF(s) into {ARCHIVE_PDFS}")
        return 0

    pdfs = _pdfs([Path(x) for x in args.extract])
    if not pdfs:
        print("no PDFs to process", file=sys.stderr)
        return 1

    results = []
    for path in pdfs:
        res = extract_one(path)
        results.append(res)
        flag = {True: "VERIFIED", False: "unverified"}[res["verified"]]
        print(f"[{flag:10s}] {res['file']}: {res['countries']} countries, "
              f"{res['rows']} rows, period={res['period_bs'] or '?'}")
        for pr in res["problems"][:3]:
            print(f"    [problem] {pr}", file=sys.stderr)

    out_path = Path(args.out) if args.out else BACKFILL_DIR / "monthly_country.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    n_rows = sum(r["rows"] for r in results)
    n_v = sum(1 for r in results if r["verified"])
    print(f"wrote {out_path} ({len(results)} docs, {n_v} verified, {n_rows} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
