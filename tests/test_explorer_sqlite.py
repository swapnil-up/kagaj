"""The browser explorer's SQLite build: tables are derived from the dataset
descriptors, with declared column types and an embedded catalog.
Build: python datasets/build_sqlite.py"""

import gzip
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "kagaj_build_sqlite", REPO_ROOT / "datasets" / "build_sqlite.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_sqlite = _load_module()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp("explorer") / "kagaj.sqlite"
    stats = build_sqlite.build(output, verbose=False)
    conn = sqlite3.connect(output)
    yield conn, stats, output
    conn.close()


def test_catalog_covers_every_descriptor_dataset(built):
    conn, _, _ = built
    index = json.loads((REPO_ROOT / "datasets" / "index.json").read_text(encoding="utf-8"))
    expected = {dataset["id"] for dataset in index["datasets"]}
    catalogued = {row[0] for row in conn.execute("SELECT dataset FROM catalog")}
    assert catalogued == expected


def test_every_table_with_data_has_a_primary(built):
    conn, stats, _ = built
    datasets_with_tables = {row[0] for row in conn.execute("SELECT DISTINCT dataset FROM catalog_tables")}
    # translations ships a document corpus, not tabular data
    assert datasets_with_tables == {"crime", "labour-migration", "water"}
    for dataset in datasets_with_tables:
        primaries = conn.execute(
            "SELECT COUNT(*) FROM catalog_tables WHERE dataset = ? AND role = 'primary'", (dataset,)
        ).fetchone()[0]
        assert primaries == 1, dataset
    assert stats["tables"] == conn.execute("SELECT COUNT(*) FROM catalog_tables").fetchone()[0]


def test_column_types_are_declared(built):
    conn, _, _ = built
    tables = [row[0] for row in conn.execute("SELECT tbl FROM catalog_tables")]
    assert tables
    for table in tables:
        info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        assert info, table
        for _, name, type_, *_ in info:
            assert type_ in {"TEXT", "INTEGER", "REAL"}, f"{table}.{name} has type {type_!r}"


def test_row_counts_match_the_descriptors(built):
    conn, _, _ = built
    index = {d["id"]: d for d in json.loads((REPO_ROOT / "datasets" / "index.json").read_text())["datasets"]}
    canonical = next(
        a for a in index["labour-migration"]["artifacts"] if a["role"] == "primary"
    )
    count = conn.execute('SELECT COUNT(*) FROM "labour_migration_panel_canonical"').fetchone()[0]
    assert count == canonical["rows"] == 70089


def test_water_is_flattened_into_branch_and_zone_tables(built):
    conn, _, _ = built
    branches = conn.execute("SELECT COUNT(*) FROM water_branches").fetchone()[0]
    zones = conn.execute("SELECT COUNT(*) FROM water_zones").fetchone()[0]
    assert branches == 7
    assert zones > 100
    sample = conn.execute("SELECT branch, days, time_from FROM water_zones WHERE days != '' LIMIT 1").fetchone()
    assert sample and "," in sample[1]


def test_gzip_companion_is_written(built):
    _, stats, output = built
    gz = output.with_name(output.name + ".gz")
    assert gz.is_file()
    assert stats["gzip_bytes"] < stats["bytes"] / 3
    with gzip.open(gz, "rb") as handle:
        assert handle.read(16) == b"SQLite format 3\x00"


def test_type_inference_keeps_leading_zeros_as_text():
    assert build_sqlite.infer_type(["007", "012"]) == "TEXT"
    assert build_sqlite.infer_type(["1", "-2"]) == "INTEGER"
    assert build_sqlite.infer_type(["1.5", "2"]) == "REAL"
    assert build_sqlite.infer_type(["2074/75"]) == "TEXT"
    assert build_sqlite.infer_type([]) == "TEXT"
    assert build_sqlite.coerce("", "INTEGER") is None
    assert build_sqlite.coerce("42", "INTEGER") == 42


def test_table_names_are_sanitised():
    assert build_sqlite.table_name("labour-migration", "panel_canonical.csv.gz") == (
        "labour_migration_panel_canonical"
    )
    assert build_sqlite.table_name("crime", "violent_monthly.csv.gz") == "crime_violent_monthly"
    assert build_sqlite.sanitize("KUKL's schedule (2083)") == "kukl_s_schedule_2083"
