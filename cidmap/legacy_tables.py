"""Validate and merge externally labelled legacy glyph tables.

The importer accepts the CSVs produced by ``output/pilot/gen-fonts`` and turns
them into the small JSON table consumed by :mod:`cidmap.legacy`.  It is
deliberately strict: every returned row must match the original catalog, code
values stay in the single-byte range, and family-level code conflicts are
rejected before anything reaches the decoder.
"""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_TABLE = Path(__file__).resolve().parent / "data" / "legacy_fonts.json"
REQUIRED_COLUMNS = ("family", "base_font", "code", "glyph", "unicode")
_JOINERS = frozenset({"\u200c", "\u200d"})


@dataclass(frozen=True)
class Row:
    family: str
    base_font: str
    code: int | None
    glyph: str
    unicode: str
    source: str
    line: int


@dataclass(frozen=True)
class Problem:
    source: str
    line: int
    message: str


def empty_table() -> dict:
    return {"schema_version": SCHEMA_VERSION, "families": {}}


def normalize_base_font(base_font: str) -> str:
    name = (base_font or "").split("+")[-1]
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _cell(row: dict, key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def read_rows(path: str | Path) -> list[Row]:
    source = str(path)
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise ValueError(
                f"{source}: missing column(s): {', '.join(missing)}")
        rows = []
        for line, record in enumerate(reader, start=2):
            raw_code = _cell(record, "code").strip()
            try:
                code = int(raw_code) if raw_code else None
            except ValueError:
                code = None
            rows.append(Row(
                family=_cell(record, "family").strip(),
                base_font=_cell(record, "base_font").strip(),
                code=code,
                glyph=_cell(record, "glyph").strip(),
                unicode=_cell(record, "unicode"),
                source=source,
                line=line,
            ))
    return rows


def _invalid_unicode(value: str) -> str | None:
    normalized = unicodedata.normalize("NFC", value)
    for char in normalized:
        if char in "\r\n\t" or char == "\ufffd":
            return f"invalid character U+{ord(char):04X}"
        category = unicodedata.category(char)
        if category in {"Cc", "Cs"}:
            return f"control character U+{ord(char):04X}"
        if category == "Cf" and char not in _JOINERS:
            return f"unsupported format character U+{ord(char):04X}"
    return None


def validate_rows(rows: list[Row],
                  catalog: list[Row] | None = None) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[tuple[str, str, int]] = set()
    family_codes: dict[tuple[str, int], tuple[str, str, int]] = {}

    for row in rows:
        if not row.family:
            problems.append(Problem(row.source, row.line, "empty family"))
        if not row.base_font:
            problems.append(Problem(row.source, row.line, "empty base_font"))
        if not row.glyph:
            problems.append(Problem(row.source, row.line, "empty glyph"))
        if row.code is None:
            problems.append(Problem(row.source, row.line, "code is not an integer"))
            continue
        if not 0 <= row.code <= 255:
            problems.append(Problem(
                row.source, row.line, "code is outside the single-byte range"))
        if row.unicode:
            reason = _invalid_unicode(row.unicode)
            if reason:
                problems.append(Problem(
                    row.source, row.line, f"unicode: {reason}"))

        key = (row.family, row.base_font, row.code)
        if key in seen:
            problems.append(Problem(
                row.source, row.line, "duplicate family/base_font/code row"))
        seen.add(key)

        value = unicodedata.normalize("NFC", row.unicode)
        family_key = (row.family, row.code)
        previous = family_codes.get(family_key)
        if previous is not None and previous[0] != value:
            first_source, first_base, first_line = previous[1:]
            problems.append(Problem(
                row.source, row.line,
                f"family code conflict with {first_source}:{first_line} "
                f"({first_base}): {previous[0]!r} != {value!r}"))
        else:
            family_codes[family_key] = (value, row.source, row.base_font, row.line)

    if catalog is not None:
        expected = {
            (row.family, row.base_font, row.code, row.glyph)
            for row in catalog
        }
        actual = {
            (row.family, row.base_font, row.code, row.glyph)
            for row in rows
        }
        for row in catalog:
            key = (row.family, row.base_font, row.code, row.glyph)
            if key not in actual:
                problems.append(Problem(
                    row.source, row.line,
                    "catalog row is missing from the returned table"))
        for row in rows:
            key = (row.family, row.base_font, row.code, row.glyph)
            if key not in expected:
                problems.append(Problem(
                    row.source, row.line,
                    "row does not match the original catalog"))
    return problems


def build_table(rows: list[Row], existing: dict | None = None) -> dict:
    table = empty_table()
    if existing:
        table = {
            "schema_version": SCHEMA_VERSION,
            "families": {
                name: {
                    "base_fonts": list(entry.get("base_fonts", ())),
                    "codes": dict(entry.get("codes", {})),
                }
                for name, entry in existing.get("families", {}).items()
            },
        }

    touched: set[str] = set()
    for row in rows:
        if row.code is None:
            raise ValueError("build_table() received an invalid code")
        family = table["families"].setdefault(
            row.family, {"base_fonts": [], "codes": {}})
        alias = normalize_base_font(row.base_font)
        if alias and alias not in family["base_fonts"]:
            family["base_fonts"].append(alias)
        value = unicodedata.normalize("NFC", row.unicode)
        if value or row.code not in family["codes"]:
            family["codes"][row.code] = value
        touched.add(row.family)

    for name in touched:
        entry = table["families"][name]
        entry["base_fonts"] = sorted(entry["base_fonts"])
        entry["codes"] = {
            int(code): value
            for code, value in sorted(
                entry["codes"].items(), key=lambda item: int(item[0]))
        }
    return table


def _validate_table(table: dict) -> None:
    if table.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported legacy table schema_version")
    families = table.get("families")
    if not isinstance(families, dict):
        raise ValueError("legacy table families must be an object")
    for name, entry in families.items():
        if not isinstance(entry, dict):
            raise ValueError(f"legacy family {name!r} is not an object")
        if not isinstance(entry.get("base_fonts"), list):
            raise ValueError(f"legacy family {name!r} base_fonts must be a list")
        if not isinstance(entry.get("codes"), dict):
            raise ValueError(f"legacy family {name!r} codes must be an object")
        for code, value in entry["codes"].items():
            if not isinstance(code, int):
                raise ValueError(f"legacy family {name!r} has a non-int code")
            if not isinstance(value, str):
                raise ValueError(f"legacy family {name!r} code {code} is not a string")


def load_table(path: str | Path = DEFAULT_TABLE) -> dict:
    p = Path(path)
    if not p.exists():
        return empty_table()
    with open(p, encoding="utf-8") as handle:
        table = json.load(handle)
    families = table.get("families")
    if isinstance(families, dict):
        for entry in families.values():
            if isinstance(entry, dict) and isinstance(entry.get("codes"), dict):
                entry["codes"] = {
                    int(code): value
                    for code, value in entry["codes"].items()
                }
    _validate_table(table)
    return table


def save_table(table: dict, path: str | Path = DEFAULT_TABLE) -> None:
    _validate_table(table)
    p = Path(path)
    os.makedirs(p.parent, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "families": {
            name: {
                "base_fonts": sorted(entry["base_fonts"]),
                "codes": {
                    str(code): value
                    for code, value in sorted(entry["codes"].items())
                },
            }
            for name, entry in sorted(table["families"].items())
        },
        "meta": {
            "updated": datetime.now(timezone.utc).isoformat(),
        },
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, p)
