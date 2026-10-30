"""Offline-checkable source provenance for the migration panel.

The manifest carries a whole-file ``pdf_sha256`` per source (see
``cmd_process.record_pdf_hash``). This stage freezes a finer fingerprint —
page count, a document text digest, and a per-page text digest — into a tracked
``datasets/labour-migration/source_attestation.json``. A third party holding the original PDFs
(or a re-download) can then verify offline that the exact pages the panel was
built from are the ones they have, without us redistributing the PDFs.

    python -m migration_parser provenance            # (re)write the attestation
    python -m migration_parser provenance --verify [DIR]

``--verify`` recomputes the attested PDFs from the cached copies (or a supplied
directory) and exits non-zero on any mismatch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kagaj_core import pdf as core_pdf
from kagaj_core import provenance

from ..paths import MIGRATION_DIR
from . import cmd_process as process

ATTESTATION = MIGRATION_DIR / "source_attestation.json"


def _sha256_text(text: str) -> str:
    return provenance.sha256_bytes(text.encode("utf-8"))


def attest_pdf(path: Path) -> dict:
    """Page count + document/per-page text digests for one PDF."""
    doc = core_pdf.open_pdf(path)
    pages = [pg.get_text("text") for pg in core_pdf.iter_pages(doc)]
    return {
        "page_count": len(pages),
        "text_sha256": _sha256_text("\n".join(pages)),
        "page_hashes": [_sha256_text(t)[:16] for t in pages],
    }


def build_attestation() -> dict:
    manifest = process.load_manifest()
    docs = []
    for e in manifest:
        dest = process.pdf_path(e)
        rec = {
            "serial": e.get("serial"),
            "doc_id": e.get("doc_id"),
            "title": e.get("title"),
            "pdf_url": e.get("pdf_url"),
            "pdf_sha256": e.get("pdf_sha256"),
            "pdf_bytes": e.get("pdf_bytes"),
        }
        if dest.exists():
            rec["cached_name"] = dest.name
            rec.update(attest_pdf(dest))
        else:
            rec["missing_cached"] = True
        docs.append(rec)
    return {
        "note": "Frozen per-page text digests of each source PDF. Verify with "
                "`migration provenance --verify` against the original PDFs; "
                "recompute matches prove the pages the panel was built from.",
        "docs": docs,
    }


def _find_pdf(rec: dict, pdf_dir: Path | None) -> Path | None:
    names = []
    if rec.get("cached_name"):
        names.append(rec["cached_name"])
    names += [f"{rec['serial']:03d}.pdf", f"{rec.get('pdf_sha256', '')}.pdf"]
    dirs = [process.PDFS_DIR] if pdf_dir is None else [pdf_dir, process.PDFS_DIR]
    for d in dirs:
        for name in names:
            cand = d / name
            if name and cand.exists():
                return cand
    return None


def verify(pdf_dir: Path | None = None) -> int:
    if not ATTESTATION.exists():
        print(f"no attestation at {ATTESTATION}; run `provenance` first",
              file=sys.stderr)
        return 2
    att = json.loads(ATTESTATION.read_text())
    bad = 0
    checked = 0
    for rec in att["docs"]:
        if rec.get("missing_cached"):
            continue
        path = _find_pdf(rec, pdf_dir)
        if path is None:
            print(f"  [missing] #{rec['serial']} {rec.get('title', '')[:40]}")
            bad += 1
            continue
        got = attest_pdf(path)
        problems = []
        if got["page_count"] != rec.get("page_count"):
            problems.append(f"page_count {got['page_count']} != {rec.get('page_count')}")
        if got["text_sha256"] != rec.get("text_sha256"):
            problems.append("text_sha256 mismatch")
        if rec.get("pdf_sha256") and process.sha256_file(path) != rec["pdf_sha256"]:
            problems.append("pdf_sha256 mismatch")
        if problems:
            print(f"  [drift] #{rec['serial']}: {', '.join(problems)}")
            bad += 1
        checked += 1
    print(f"verified {checked} source PDFs; {bad} problem(s)")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration provenance")
    p.add_argument("--verify", nargs="?", const="", default=None,
                   metavar="PDF_DIR", help="verify against cached/other PDFs")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    if args.verify is not None:
        pdf_dir = Path(args.verify) if args.verify else None
        return verify(pdf_dir)

    att = build_attestation()
    n = sum(1 for d in att["docs"] if "page_count" in d)
    if n == 0 and ATTESTATION.exists():
        print(f"skip {ATTESTATION.name}: no cached PDFs to attest; kept existing file")
        return 0
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    ATTESTATION.write_text(json.dumps(att, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {ATTESTATION.name}: {n} docs attested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
