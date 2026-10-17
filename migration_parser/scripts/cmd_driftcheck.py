"""Detect upstream source-PDF drift for the migration manifests.

Every source PDF is stamped with a ``pdf_sha256`` when first fetched (see
``cmd_process.record_pdf_hash``; the archive backfill stamps
``source_pdf_sha256`` in ``cmd_backfill.fetch_manifest``). DoFE occasionally
revises or re-scans a PDF in place; without this check a rebuild would silently
absorb the change. This stage compares the recorded hash against

* the cached file on disk (default), and
* the live URL when ``--recheck`` is given (network).

Both the live ``migration_manifest.json`` and the archive
``migration_archive_manifest.json`` are checked — the archive PDFs are the ones
least likely to be re-examined by anyone else, so they get the same treatment.

Writes ``output/migration/drift.json`` and exits non-zero on any drift (missing
hash, changed-on-disk, or changed-upstream) so CI can catch it.

    python -m migration_parser driftcheck            # cached files only
    python -m migration_parser driftcheck --recheck  # also re-download upstream
"""

from __future__ import annotations

import argparse
import json
import sys

import requests
import urllib3

from ..paths import BILLTRACKER_ROOT, MIGRATION_OUTPUT_DIR, REPO_ROOT
from . import cmd_process as process

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ARCHIVE_MANIFEST = BILLTRACKER_ROOT / "migration_archive_manifest.json"
ARCHIVE_PDFS = MIGRATION_OUTPUT_DIR / "archive_pdfs"


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _upstream_sha256(url: str) -> str | None:
    try:
        r = requests.get(url, headers=process.HEADERS, timeout=120, verify=False)
        r.raise_for_status()
        return _sha256_bytes(r.content)
    except requests.exceptions.RequestException as e:
        print(f"  [recheck error] {url}: {e}", file=sys.stderr)
        return None


def _archive_path(e: dict):
    # ``local_path`` is authoritative: re-resolving the manifest renumbers
    # serials, but the downloaded bytes keep their original filename.
    lp = e.get("local_path")
    if lp:
        p = REPO_ROOT / lp
        if p.exists():
            return p
    return ARCHIVE_PDFS / f"{e['serial']:03d}_{e['period_bs'].replace(' ', '_')}.pdf"


def archive_findings(recheck: bool) -> list[dict]:
    """Drift findings for the archive.org backfill manifest (``source_pdf_sha256``)."""
    if not ARCHIVE_MANIFEST.exists():
        return []
    entries = json.loads(ARCHIVE_MANIFEST.read_text())
    out: list[dict] = []
    for e in entries:
        if e.get("status") != "fetched":
            continue
        rec = {
            "source_kind": "archive_org",
            "serial": e.get("serial"),
            "title": e.get("title"),
            "pdf_url": e.get("wayback_url"),
            "recorded": e.get("source_pdf_sha256"),
            "state": "ok",
        }
        dest = _archive_path(e)
        if not dest.exists():
            rec["state"] = "missing_cached"
            out.append(rec)
            continue
        current = process.sha256_file(dest)
        if not e.get("source_pdf_sha256"):
            rec["state"] = "unhashed"
        elif current != e["source_pdf_sha256"]:
            rec["state"] = "changed_on_disk"
            rec["observed"] = current
        if recheck and e.get("wayback_url"):
            up = _upstream_sha256(e["wayback_url"])
            if up and e.get("source_pdf_sha256") and up != e["source_pdf_sha256"]:
                rec["state"] = "changed_upstream"
                rec["observed"] = up
        out.append(rec)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration driftcheck")
    p.add_argument("--recheck", action="store_true",
                   help="re-download each pdf_url and compare to the recorded hash")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    manifest = process.load_manifest()
    findings: list[dict] = []
    for e in manifest:
        dest = process.pdf_path(e)
        rec = {
            "source_kind": "manifest",
            "serial": e.get("serial"),
            "title": e.get("title"),
            "pdf_url": e.get("pdf_url"),
            "recorded": e.get("pdf_sha256"),
            "state": "ok",
        }
        if not dest.exists():
            rec["state"] = "missing_cached"
            findings.append(rec)
            continue
        current = process.sha256_file(dest)
        if not e.get("pdf_sha256"):
            rec["state"] = "unhashed"
        elif current != e["pdf_sha256"]:
            rec["state"] = "changed_on_disk"
            rec["observed"] = current
        if args.recheck and e.get("pdf_url"):
            up = _upstream_sha256(e["pdf_url"])
            if up and e.get("pdf_sha256") and up != e["pdf_sha256"]:
                rec["state"] = "changed_upstream"
                rec["observed"] = up
        findings.append(rec)

    archive = archive_findings(args.recheck)
    findings.extend(archive)

    drift = [f for f in findings if f["state"] != "ok"]
    out = {
        "recheck": args.recheck,
        "checked": len(findings),
        "archive_checked": len(archive),
        "drift": drift,
        "note": "recorded hashes are stamped at fetch (cmd_process for the live "
                "manifest, cmd_backfill for the archive manifest); a non-ok state "
                "means the source may have been revised in place.",
    }
    MIGRATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = MIGRATION_OUTPUT_DIR / "drift.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    for f in drift:
        print(f"  [{f['state']}] #{f['serial']} {f.get('title','')[:50]}")
    print(f"checked {len(findings)} docs; {len(drift)} drift finding(s) -> {path}")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
