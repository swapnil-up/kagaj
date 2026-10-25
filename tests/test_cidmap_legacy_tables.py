import csv

import pytest

from cidmap import legacy
from cidmap.legacy_tables import (
    build_table,
    load_table,
    read_rows,
    save_table,
    validate_rows,
)


HEADER = ["family", "base_font", "code", "glyph", "unicode"]


def _write(path, rows, header=HEADER):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_table_imports_and_decodes(tmp_path):
    rows = [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
        ["gen-test", "ABCDEF+Gen_Test", 3, "MT3", "्"],
        ["gen-test", "ABCDEF+Gen_Test", 4, "MT4", ""],
    ]
    catalog = _write(tmp_path / "catalog.csv", rows)
    labelled = _write(tmp_path / "codes.csv", rows)

    parsed = read_rows(labelled)
    assert validate_rows(parsed, read_rows(catalog)) == []
    table = build_table(parsed)
    path = tmp_path / "legacy_fonts.json"
    save_table(table, path)
    loaded = load_table(path)
    assert loaded["families"]["gen-test"]["codes"] == {
        2: "क", 3: "्", 4: "",
    }

    try:
        legacy.reload_table(path)
        assert legacy.family("ABCDEF+Gen_Test") == "gen-test"
        assert legacy.supported("gen-test")
        assert legacy.decode_cids([2, 3, 4], "gen-test") == "क्"
        assert legacy.decode_cids([9], "gen-test") is None
    finally:
        legacy.reload_table()


def test_family_code_conflict_is_rejected(tmp_path):
    rows = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
        ["gen-test", "FEDCBA+Gen_Test", 2, "MT2", "ख"],
    ])
    problems = validate_rows(read_rows(rows))
    assert any("family code conflict" in problem.message
               for problem in problems)


def test_duplicate_row_is_rejected(tmp_path):
    rows = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
    ])
    problems = validate_rows(read_rows(rows))
    assert any("duplicate" in problem.message for problem in problems)


def test_catalog_mismatch_is_rejected(tmp_path):
    catalog = _write(tmp_path / "catalog.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", ""],
        ["gen-test", "ABCDEF+Gen_Test", 3, "MT3", ""],
    ])
    returned = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
        ["gen-test", "ABCDEF+Gen_Test", 4, "MT4", "ख"],
    ])
    problems = validate_rows(read_rows(returned), read_rows(catalog))
    messages = {problem.message for problem in problems}
    assert "catalog row is missing from the returned table" in messages
    assert "row does not match the original catalog" in messages


@pytest.mark.parametrize("value", ["\ufffd", "\x01", "\n"])
def test_invalid_unicode_is_rejected(tmp_path, value):
    rows = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", value],
    ])
    problems = validate_rows(read_rows(rows))
    assert any(problem.message.startswith("unicode:") for problem in problems)


def test_missing_required_column_is_rejected(tmp_path):
    rows = _write(
        tmp_path / "codes.csv",
        [["gen-test", "ABCDEF+Gen_Test", 2, "MT2"]],
        header=["family", "base_font", "code", "glyph"],
    )
    with pytest.raises(ValueError, match="missing column"):
        read_rows(rows)


def test_cli_requires_filled_labels(tmp_path, capsys):
    from cidmap.cli import main

    path = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", ""],
    ])
    assert main(["legacy-import", str(path), "--table",
                 str(tmp_path / "table.json")]) == 1
    assert "no Unicode labels" in capsys.readouterr().err


def test_cli_applies_and_reports(tmp_path, capsys):
    from cidmap.cli import main
    from cidmap.legacy_tables import load_table

    path = _write(tmp_path / "codes.csv", [
        ["gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क"],
        ["gen-test", "ABCDEF+Gen_Test", 3, "MT3", ""],
    ])
    table = tmp_path / "table.json"
    report = tmp_path / "report.json"
    assert main([
        "legacy-import", str(path), "--table", str(table),
        "--apply", "--json", str(report),
    ]) == 0
    assert load_table(table)["families"]["gen-test"]["codes"] == {
        2: "क", 3: "",
    }
    assert report.exists()
    assert "Wrote" in capsys.readouterr().err


def test_blank_rows_do_not_erase_existing_labels():
    from cidmap.legacy_tables import Row

    existing = build_table([
        Row("gen-test", "ABCDEF+Gen_Test", 2, "MT2", "क", "a", 2),
    ])
    merged = build_table([
        Row("gen-test", "ABCDEF+Gen_Test", 2, "MT2", "", "b", 2),
        Row("gen-test", "ABCDEF+Gen_Test", 3, "MT3", "", "b", 3),
    ], existing=existing)
    assert merged["families"]["gen-test"]["codes"] == {2: "क", 3: ""}
