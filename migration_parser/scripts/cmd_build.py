"""One-command reproducible build + packaging for the migration datasets.

Runs the whole pipeline end to end from cached inputs, then writes the shipped
artifacts and a manifest:

  extract (process/annex/agencies/series) → normalize → reconcile → verify →
  crosscheck → package

Packaging gzips ``migration/panel_canonical.csv`` to ``panel_canonical.csv.gz``
(deterministic, mtime=0) and writes ``migration/build.json`` (git revision,
timestamps, row counts, SHA-256 checksums, audit results) plus the
machine-readable ``migration/codebook.json``.

    python -m migration_parser build                 # offline, from cached PDFs
    python -m migration_parser build --scrape        # refresh manifest first
    python -m migration_parser build --skip-extract  # re-normalise/verify only
    python -m migration_parser build --allow-download
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from .. import codebook, normalize
from ..paths import MIGRATION_DIR, MIGRATION_MANIFEST, MIGRATION_OPENDATA_DIR, REPO_ROOT
from . import (
    cmd_agencies,
    cmd_annex,
    cmd_crosscheck,
    cmd_normalize,
    cmd_process,
    cmd_reconcile,
    cmd_scrape,
    cmd_series,
    cmd_verify,
)

SHIPPED = ["panel.csv", "panel_canonical.csv.gz", "agencies.csv", "series.csv"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_count(path: Path) -> int | None:
    if not path.exists():
        return None
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)  # header
        return sum(1 for _ in r)


def _git() -> dict:
    def run(*a):
        try:
            return subprocess.run(["git", *a], cwd=REPO_ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""
    return {
        "commit": run("rev-parse", "HEAD"),
        "describe": run("describe", "--tags", "--always", "--dirty"),
        "dirty": bool(run("status", "--porcelain")),
    }


def gunzip_panel() -> Path:
    """Deterministically gzip panel_canonical.csv -> panel_canonical.csv.gz."""
    src = MIGRATION_DIR / "panel_canonical.csv"
    dst = MIGRATION_DIR / "panel_canonical.csv.gz"
    data = src.read_bytes()
    with dst.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(data)
    print(f"wrote {dst.name} ({len(data) / 1e6:.1f} MB -> {dst.stat().st_size / 1e6:.1f} MB)")
    return dst


def _verify_columns() -> None:
    """Fail loudly if the codebook columns drift from the shipped headers."""
    expected = {
        "panel.csv": list(cmd_process.PANEL_COLUMNS),
        "panel_canonical.csv.gz": cmd_process.PANEL_COLUMNS + cmd_normalize.PANEL_EXTRA
                                  + cmd_reconcile.EXTRA,
        "agencies.csv": list(cmd_agencies.AGENCY_COLUMNS),
        "series.csv": list(cmd_series.COLUMNS),
    }
    for name, cols in expected.items():
        known = codebook.COLUMNS[name]
        missing = [c for c in cols if c not in known]
        extra = [c for c in known if c not in cols]
        if missing or extra:
            raise SystemExit(f"codebook drift in {name}: missing={missing} extra={extra}")


def _vocabularies() -> dict:
    channels = normalize.canonical_channels()
    return {
        "section": ["country", "district"],
        "gender": ["male", "female", "total"],
        "row_type": ["detail", "total", "grand_total"],
        "granularity": ["month", "year", "measure", ""],
        "doc_type": sorted(normalize.reconciliation()["granularity"].keys()),
        "channel_canonical": {
            name: {"label": m.get("label", name), "class": m.get("class", "unknown")}
            for name, m in sorted(channels.items())
        },
    }


def write_codebook(build: dict) -> Path:
    out = {
        "schema_version": codebook.SCHEMA_VERSION,
        "generated_at": build["generated_at"],
        "build": {"commit": build["git"]["commit"], "describe": build["git"]["describe"]},
        "datasets": {},
        "vocabularies": _vocabularies(),
    }
    for name, meta in codebook.DATASETS.items():
        out["datasets"][name] = {
            **meta,
            "rows": build["files"][name]["rows"],
            "sha256": build["files"][name]["sha256"],
            "columns": codebook.COLUMNS[name],
        }
    path = MIGRATION_DIR / "codebook.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.name}")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration build")
    p.add_argument("--scrape", action="store_true", help="refresh manifest (network)")
    p.add_argument("--skip-extract", action="store_true", help="skip PDF extraction stages")
    p.add_argument("--allow-download", action="store_true",
                   help="allow downloading missing PDFs (default: offline)")
    p.add_argument("--skip-crosscheck", action="store_true")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    online = args.allow_download
    audits: dict[str, object] = {}
    t0 = time.time()

    if args.scrape:
        cmd_scrape.main([])
    elif not MIGRATION_MANIFEST.exists():
        print("error: manifest missing; run with --scrape", file=sys.stderr)
        return 2

    if not args.skip_extract:
        # Rebuild per-doc CSVs from scratch so stale outputs can't leak into
        # panel.csv (docs are regenerated by the process/annex/agencies stages).
        if cmd_process.DOCS_DIR.exists():
            for f in cmd_process.DOCS_DIR.glob("*.csv"):
                f.unlink()
        cmd_process.main(["--force"])
        cmd_annex.main([])
        cmd_agencies.main([])
        cmd_series.main([] if online else ["--no-download"])

    cmd_normalize.main([])

    rc = cmd_reconcile.main([])
    audits["reconcile"] = {"exit": rc, "ok": rc == 0}

    rc = cmd_verify.main([])
    audits["verify"] = {"exit": rc, "ok": rc == 0}

    if args.skip_crosscheck or not MIGRATION_OPENDATA_DIR.exists():
        if not MIGRATION_OPENDATA_DIR.exists():
            print(f"skip crosscheck: {MIGRATION_OPENDATA_DIR} not present", file=sys.stderr)
        audits["crosscheck"] = {"exit": None, "ok": None, "skipped": True}
    else:
        rc = cmd_crosscheck.main([])
        audits["crosscheck"] = {"exit": rc, "ok": rc == 0}

    try:
        _verify_columns()
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    gunzip_panel()

    build = {
        "schema_version": codebook.SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_s": round(time.time() - t0, 1),
        "git": _git(),
        "audits": audits,
        "files": {},
    }
    for name in SHIPPED:
        path = MIGRATION_DIR / name
        build["files"][name] = {
            "rows": _row_count(path),
            "bytes": path.stat().st_size if path.exists() else None,
            "sha256": _sha256(path) if path.exists() else None,
        }

    (MIGRATION_DIR / "build.json").write_text(
        json.dumps(build, indent=2, ensure_ascii=False) + "\n")
    print("wrote build.json")

    write_codebook(build)

    failed = [k for k, v in audits.items() if v.get("ok") is False]
    if failed:
        print(f"BUILD AUDIT FAILED: {', '.join(failed)}")
        return 1
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
