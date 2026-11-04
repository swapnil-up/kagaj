#!/usr/bin/env python3
"""Build one SQLite database from datasets/index.json for the browser explorer.

Reads every CSV artifact declared in the dataset descriptors (raw extracts are
excluded — canonical/rollup/reference files are the analysis surface), flattens
the water schedule JSON, and embeds the descriptor metadata as `catalog` tables
so the frontend needs nothing but this one file.

    python datasets/build_sqlite.py [--output path]

Output defaults to output/explorer/kagaj.sqlite (gitignored).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = REPO_ROOT / "datasets" / "index.json"
DEFAULT_OUTPUT = REPO_ROOT / "output" / "explorer" / "kagaj.sqlite"

# Raw extracts are provenance, not an analysis surface: they duplicate the
# canonical files at larger size.
EXCLUDED_ROLES = {"raw"}
# The analysis surface: these are always included regardless of size.
INCLUDED_ROLES = {"primary", "canonical", "rollup"}
# Anything smaller than this is a lookup/coverage table worth having alongside
# the analysis files. Bigger specialist tables (agencies, series, the archive
# backfill) stay in their CSVs — they are different units or unfinished work.
TABLE_SOURCE_LIMIT = 2_000_000

INT_RE = re.compile(r"-?\d+")
REAL_RE = re.compile(r"-?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")


def sanitize(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def table_name(dataset: str, artifact_path: str) -> str:
    stem = re.sub(r"\.(csv\.gz|csv)$", "", Path(artifact_path).name)
    return sanitize(f"{dataset}_{stem}")


def _is_integer(values: list[str]) -> bool:
    for value in values:
        if not INT_RE.fullmatch(value):
            return False
        digits = value.lstrip("-")
        if len(digits) > 1 and digits.startswith("0"):
            return False
    return True


def _is_real(values: list[str]) -> bool:
    for value in values:
        if not REAL_RE.fullmatch(value):
            return False
        digits = value.lstrip("-").lstrip("+")
        if len(digits) > 1 and digits.startswith("0") and "." not in digits and "e" not in digits.lower():
            return False
    return True


def infer_type(values: list[str]) -> str:
    if not values:
        return "TEXT"
    if _is_integer(values):
        return "INTEGER"
    if _is_real(values):
        return "REAL"
    return "TEXT"


def coerce(value: str, kind: str) -> Any:
    if value == "":
        return None
    if kind == "INTEGER":
        return int(value)
    if kind == "REAL":
        return float(value)
    return value


def source_bytes(path: Path) -> int:
    if path.suffix == ".gz":
        total = 0
        with gzip.open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                total += len(chunk)
        return total
    return path.stat().st_size


def read_csv(path: Path) -> tuple[list[str], list[str], list[list[Any]]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[operator]
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            raise ValueError(f"{path} has no header row")
        rows = [row for row in reader]
    columns = [sanitize(col) or f"col_{i}" for i, col in enumerate(header)]
    if len(set(columns)) != len(columns):
        seen: dict[str, int] = {}
        fixed = []
        for col in columns:
            seen[col] = seen.get(col, 0) + 1
            fixed.append(col if seen[col] == 1 else f"{col}_{seen[col]}")
        columns = fixed
    width = len(columns)
    kinds = []
    for index in range(width):
        column_values = [row[index] for row in rows if index < len(row) and row[index] != ""]
        kinds.append(infer_type(column_values))
    typed: list[list[Any]] = []
    for row in rows:
        padded = row[:width] + [""] * (width - len(row))
        typed.append([coerce(padded[i], kinds[i]) for i in range(width)])
    return columns, kinds, typed


def create_table(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    kinds: list[str],
    rows: list[list[Any]],
) -> None:
    definitions = ", ".join(f'"{col}" {kind}' for col, kind in zip(columns, kinds))
    conn.execute(f'CREATE TABLE "{table}" ({definitions})')
    if rows:
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)


def _join(values: Any) -> str | None:
    parts = [str(v) for v in (values or []) if v not in (None, "")]
    return "; ".join(parts) or None


def flatten_water(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Split schedule.json into a branch table and a zone-level table."""
    schedule_path = REPO_ROOT / "datasets" / "water" / "schedule.json"
    if not schedule_path.is_file():
        return []
    data = json.loads(schedule_path.read_text(encoding="utf-8"))
    branches: list[list[Any]] = []
    zones: list[list[Any]] = []
    for branch in data.get("branches", []):
        reservoirs = branch.get("reservoirs") or []
        zone_count = sum(len(r.get("zones") or []) for r in reservoirs)
        branches.append([
            branch.get("branch"),
            branch.get("branch_np"),
            branch.get("branch_en"),
            branch.get("month_bs"),
            branch.get("month_key"),
            branch.get("source_file"),
            branch.get("source_url"),
            len(reservoirs),
            zone_count,
        ])
        for reservoir in reservoirs:
            for zone in reservoir.get("zones") or []:
                zones.append([
                    branch.get("branch"),
                    branch.get("month_key"),
                    reservoir.get("name_np"),
                    reservoir.get("name_en"),
                    zone.get("dma"),
                    zone.get("label"),
                    ",".join(str(d) for d in (zone.get("days") or []) if d is not None),
                    zone.get("time_from"),
                    zone.get("time_to"),
                    _join(zone.get("areas_en")),
                    _join(zone.get("areas_np")),
                    _join(zone.get("contacts")),
                    zone.get("notes"),
                    branch.get("source_url"),
                ])
    tables = []
    create_table(
        conn, "water_branches",
        ["branch", "branch_np", "branch_en", "month_bs", "month_key", "source_file",
         "source_url", "n_reservoirs", "n_zones"],
        ["TEXT"] * 7 + ["INTEGER", "INTEGER"],
        branches,
    )
    tables.append(("water_branches", "canonical", "One row per branch × month, from schedule.json."))
    create_table(
        conn, "water_zones",
        ["branch", "month_key", "reservoir_np", "reservoir_en", "dma", "label", "days",
         "time_from", "time_to", "areas_en", "areas_np", "contacts", "notes", "source_url"],
        ["TEXT"] * 14,
        zones,
    )
    tables.append((
        "water_zones",
        "primary",
        "One row per zone; `days` is the comma-joined delivery day of the month "
        "(match day 8 with ',' || days || ',' LIKE '%,8,%').",
    ))
    return tables


CATALOG_SCHEMA = """
CREATE TABLE catalog (
    dataset TEXT PRIMARY KEY,
    title TEXT,
    status TEXT,
    description TEXT,
    grain TEXT,
    coverage_start TEXT,
    coverage_end TEXT,
    coverage_note TEXT,
    sources TEXT,
    verification TEXT,
    pipeline TEXT,
    docs TEXT,
    notes TEXT,
    license TEXT
);
CREATE TABLE catalog_tables (
    dataset TEXT,
    tbl TEXT,
    role TEXT,
    rows INTEGER,
    description TEXT,
    PRIMARY KEY (dataset, tbl)
);
"""


def write_catalog(conn: sqlite3.Connection, index: dict[str, Any], built: dict[str, list[tuple[str, str, str]]]) -> None:
    conn.executescript(CATALOG_SCHEMA)
    for dataset in index.get("datasets", []):
        dataset_id = dataset["id"]
        coverage = dataset.get("coverage") or {}
        conn.execute(
            "INSERT INTO catalog VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                dataset_id,
                dataset.get("title"),
                dataset.get("status"),
                dataset.get("description"),
                dataset.get("grain"),
                coverage.get("start"),
                coverage.get("end"),
                coverage.get("note"),
                json.dumps(dataset.get("sources") or [], ensure_ascii=False),
                json.dumps(dataset.get("verification") or {}, ensure_ascii=False),
                json.dumps(dataset.get("pipeline") or {}, ensure_ascii=False),
                json.dumps(dataset.get("docs") or [], ensure_ascii=False),
                json.dumps(dataset.get("notes") or [], ensure_ascii=False),
                json.dumps(dataset.get("license") or {}, ensure_ascii=False),
            ),
        )
        for table, role, description in built.get(dataset_id, []):
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            conn.execute(
                "INSERT INTO catalog_tables VALUES (?,?,?,?,?)",
                (dataset_id, table, role, row, description),
            )
    conn.commit()


def build(output: Path = DEFAULT_OUTPUT, verbose: bool = True) -> dict[str, Any]:
    if not INDEX_PATH.is_file():
        raise SystemExit("datasets/index.json missing — run: python -m kagaj_core.manifest index")
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(output)
    built: dict[str, list[tuple[str, str, str]]] = {}
    try:
        for dataset in index.get("datasets", []):
            dataset_id = dataset["id"]
            built[dataset_id] = []
            for artifact in dataset.get("artifacts", []):
                fmt = artifact.get("format")
                if fmt not in {"csv", "csv.gz"} or artifact.get("role") in EXCLUDED_ROLES:
                    continue
                path = REPO_ROOT / "datasets" / dataset_id / artifact["path"]
                if not path.is_file():
                    continue
                role = artifact.get("role")
                if role not in INCLUDED_ROLES and source_bytes(path) > TABLE_SOURCE_LIMIT:
                    if verbose:
                        print(f"  skip {artifact['path']} (role={role}, > {TABLE_SOURCE_LIMIT // 1_000_000} MB)")
                    continue
                table = table_name(dataset_id, artifact["path"])
                columns, kinds, rows = read_csv(path)
                create_table(conn, table, columns, kinds, rows)
                built[dataset_id].append(
                    (table, role, artifact.get("description") or f"{artifact['path']} ({role})")
                )
                if verbose:
                    print(f"  {table}: {len(rows)} rows × {len(columns)} cols")
            if dataset_id == "water":
                for table, role, description in flatten_water(conn):
                    built[dataset_id].append((table, role, description))
                    if verbose:
                        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                        print(f"  {table}: {count} rows (flattened from schedule.json)")

        write_catalog(conn, index, built)
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    gz_path = output.with_name(output.name + ".gz")
    with open(output, "rb") as source, gzip.open(gz_path, "wb", compresslevel=6) as target:
        shutil.copyfileobj(source, target)

    stats = {
        "output": str(output),
        "bytes": output.stat().st_size,
        "gzip_bytes": gz_path.stat().st_size,
        "datasets": len(built),
        "tables": sum(len(v) for v in built.values()),
    }
    if verbose:
        print(
            f"wrote {output.relative_to(REPO_ROOT)} "
            f"({stats['bytes'] / 1e6:.1f} MB, {stats['gzip_bytes'] / 1e6:.1f} MB gz, "
            f"{stats['tables']} tables)"
        )
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python datasets/build_sqlite.py", description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="sqlite file to write")
    args = parser.parse_args(argv)
    started = time.time()
    stats = build(args.output)
    print(f"built in {time.time() - started:.1f}s")
    return 0 if stats["tables"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
