"""One-command reproducible build + packaging for the migration datasets.

Runs the whole pipeline end to end from cached inputs, then writes the shipped
artifacts and a manifest:

  extract (process/annex/agencies/series) → normalize → reconcile → verify →
  crosscheck → package

Packaging gzips the raw and reconciled panels (deterministic, mtime=0) and writes
``datasets/labour-migration/build.json`` (git revision,
timestamps, row counts, SHA-256 checksums, audit results) plus the
machine-readable ``datasets/labour-migration/codebook.json``.

    python -m migration_parser build                 # offline, from cached PDFs
    python -m migration_parser build --scrape        # refresh manifest first
    python -m migration_parser build --skip-extract  # re-normalise/verify only
    python -m migration_parser build --allow-download
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
from pathlib import Path

from kagaj_core import provenance

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

SHIPPED = ["panel.csv.gz", "panel_canonical.csv.gz", "panel_rollup.csv.gz",
           "agencies.csv", "series.csv", "period_windows.csv"]


def _sha256(path: Path) -> str:
    return provenance.sha256_file(path)


def _row_count(path: Path) -> int | None:
    if not path.exists():
        return None
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)  # header
        return sum(1 for _ in r)


def _git() -> dict:
    return provenance.git_state(REPO_ROOT)


def gunzip_panel(src_name: str = "panel_canonical.csv",
                 dst_name: str = "panel_canonical.csv.gz") -> Path:
    """Deterministically gzip a shipped CSV (mtime=0 -> stable bytes)."""
    src = MIGRATION_DIR / src_name
    dst = MIGRATION_DIR / dst_name
    if not src.exists():
        if dst.exists():
            return dst
        raise FileNotFoundError(src)
    data = src.read_bytes()
    with dst.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(data)
    print(f"wrote {dst.name} ({len(data) / 1e6:.1f} MB -> {dst.stat().st_size / 1e6:.1f} MB)")
    return dst


def _verify_columns() -> None:
    """Fail loudly if the codebook columns drift from the shipped headers."""
    canonical_cols = cmd_process.PANEL_COLUMNS + cmd_normalize.PANEL_EXTRA + cmd_reconcile.EXTRA
    expected = {
        "panel.csv.gz": list(cmd_process.PANEL_COLUMNS),
        "panel_canonical.csv.gz": canonical_cols,
        "panel_rollup.csv.gz": canonical_cols,
        "agencies.csv": list(cmd_agencies.AGENCY_COLUMNS),
        "series.csv": list(cmd_series.COLUMNS),
        "period_windows.csv": PERIOD_WINDOW_COLUMNS,
    }
    for name, cols in expected.items():
        known = codebook.COLUMNS[name]
        missing = [c for c in cols if c not in known]
        extra = [c for c in known if c not in cols]
        if missing or extra:
            raise SystemExit(f"codebook drift in {name}: missing={missing} extra={extra}")


PERIOD_WINDOW_COLUMNS = ["period_bs", "fiscal_year", "period_ad_start",
                         "period_ad_end", "doc_id", "granularity"]


def _open(path: Path):
    return gzip.open if path.suffix == ".gz" else open


def _col_values(path: Path, col: str) -> list[str]:
    with _open(path)(path, "rt", newline="", encoding="utf-8") as f:
        return sorted({row.get(col, "") for row in csv.DictReader(f)})


def _vocabularies() -> dict:
    """Controlled vocabularies read from the shipped data (never hard-coded)."""
    canon = MIGRATION_DIR / "panel_canonical.csv.gz"
    series = MIGRATION_DIR / "series.csv"
    agencies = MIGRATION_DIR / "agencies.csv"
    channels = normalize.canonical_channels()
    return {
        "section": _col_values(canon, "section"),
        "gender": _col_values(canon, "gender"),
        "row_type": _col_values(canon, "row_type"),
        "granularity": _col_values(canon, "granularity"),
        "doc_type": _col_values(canon, "doc_type"),
        "channel_class": sorted({m.get("class", "unknown") for m in channels.values()}),
        "channel_reviewed": _col_values(canon, "channel_reviewed"),
        "analysis_safe": _col_values(canon, "analysis_safe"),
        "analysis_safe_permissive": _col_values(canon, "analysis_safe_permissive"),
        "entity_type": _col_values(canon, "entity_type"),
        "channel_canonical": {
            name: {"label": m.get("label", name), "class": m.get("class", "unknown")}
            for name, m in sorted(channels.items())
        },
        "series": {
            "unit": _col_values(series, "unit"),
            "year_basis": _col_values(series, "year_basis"),
            "metric": _col_values(series, "metric"),
            "dimension": _col_values(series, "dimension"),
            "gender": _col_values(series, "gender"),
        },
        "agencies": {"measure": _col_values(agencies, "measure")},
    }


def _check_vocabularies(vocab: dict) -> None:
    """Fail if the data contains a value not documented in codebook.EXPECTED_VOCAB.

    Watching only columns let ``year_basis=snapshot`` slip through silently; this
    watches values too.
    """
    for dataset, cols in codebook.EXPECTED_VOCAB.items():
        for col, allowed in cols.items():
            if dataset == "series.csv":
                observed = set(vocab["series"].get(col, []))
            elif dataset == "agencies.csv":
                observed = set(vocab["agencies"].get(col, []))
            else:
                observed = set(vocab.get(col, []))
            extra = observed - allowed
            if extra:
                raise SystemExit(
                    f"vocabulary drift: {dataset}.{col} has undocumented values {sorted(extra)}; "
                    f"add them to codebook.EXPECTED_VOCAB and datasets/labour-migration/README.md")


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


def write_period_windows() -> Path:
    """Publish the distinct reporting windows for date-based merges (tracked)."""
    src = MIGRATION_DIR / "panel_canonical.csv"
    groups: dict[tuple, set[str]] = {}
    with src.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r["period_bs"], r["reconciled_fiscal_year"], r["period_ad_start"],
                   r["period_ad_end"], r["granularity"])
            groups.setdefault(key, set()).add(r["doc_id"])
    rows = [
        {"period_bs": pbs, "fiscal_year": fy, "period_ad_start": start,
         "period_ad_end": end, "doc_id": ";".join(sorted(docs)), "granularity": gran}
        for (pbs, fy, start, end, gran), docs in groups.items()
    ]
    rows.sort(key=lambda r: (r["period_ad_start"], r["period_bs"], r["granularity"]))
    path = MIGRATION_DIR / "period_windows.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PERIOD_WINDOW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path.name} ({len(rows)} windows)")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="migration build")
    p.add_argument("--scrape", action="store_true", help="refresh manifest (network)")
    p.add_argument("--skip-extract", action="store_true", help="skip PDF extraction stages")
    p.add_argument("--allow-download", action="store_true",
                   help="allow downloading missing PDFs (default: offline)")
    p.add_argument("--skip-crosscheck", action="store_true")
    p.add_argument("--require-clean", action="store_true",
                   help="fail if the git tree is dirty (used for the shipped fingerprint)")
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

    if args.skip_crosscheck:
        audits["crosscheck"] = {"exit": None, "ok": None, "skipped": True}
    else:
        if online and not MIGRATION_OPENDATA_DIR.exists():
            try:
                cmd_crosscheck.download_opendata()
            except Exception as e:  # noqa: BLE001 - crosscheck is optional
                print(f"warn: opendata download failed: {e}", file=sys.stderr)
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

    gunzip_panel("panel.csv", "panel.csv.gz")
    gunzip_panel()
    gunzip_panel("panel_rollup.csv", "panel_rollup.csv.gz")
    write_period_windows()

    vocab = _vocabularies()
    try:
        _check_vocabularies(vocab)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 1

    git = _git()
    if args.require_clean and git["dirty"]:
        print("error: --require-clean set but git tree is dirty; commit first", file=sys.stderr)
        return 1

    build = {
        "schema_version": codebook.SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "duration_s": round(time.time() - t0, 1),
        "git": git,
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

    try:
        from . import cmd_provenance
        cmd_provenance.main([])
    except Exception as e:  # noqa: BLE001 - provenance is best-effort in build
        print(f"warn: provenance attestation failed: {e}", file=sys.stderr)

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
