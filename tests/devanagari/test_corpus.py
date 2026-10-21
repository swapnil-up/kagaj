"""Schema and coverage checks for the Devanagari specification corpus.

This module deliberately imports no normalizer. It defines the contract that
the corpus must satisfy before issue #5 adds runtime code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CASES_PATH = HERE / "cases.jsonl"

REQUIRED_FIELDS = ("id", "category", "rule", "input", "expected", "source", "notes")

CATEGORIES = {
    "order",
    "reph",
    "matra",
    "nukta",
    "zwj-zwnj",
    "conjunct",
    "invalid",
    "digits-punctuation",
    "valid-word",
    "ocr-snippet",
}

REQUIRED_CATEGORIES = {
    "order",
    "reph",
    "matra",
    "nukta",
    "zwj-zwnj",
    "invalid",
    "digits-punctuation",
    "valid-word",
    "ocr-snippet",
}

OPERATIONS = {"normalize", "canonical_key", "segment", "invalid", "repair"}

SOURCE_RE = re.compile(
    r"^(?P<path>(?:datasets|tests|cidmap|docs|archive|redbook_parser|water_parser)/[^:]+):(?P<line>\d+)$"
)


class CorpusError(ValueError):
    """Raised when the JSONL corpus violates its schema."""


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """Load and validate every JSONL record, failing on the first defect."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise CorpusError(f"{path}: corpus is empty")

    cases: list[dict] = []
    seen_ids: set[str] = set()

    for lineno, line in enumerate(lines, 1):
        where = f"{path}:{lineno}"
        if not line.strip():
            raise CorpusError(f"{where}: blank line is not a JSON object")

        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{where}: invalid JSON: {exc.msg}") from exc

        if not isinstance(record, dict):
            raise CorpusError(f"{where}: record must be a JSON object")

        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            raise CorpusError(f"{where}: missing fields: {', '.join(missing)}")

        for field in REQUIRED_FIELDS:
            value = record[field]
            if not isinstance(value, str):
                raise CorpusError(f"{where}: {field} must be a string")
            if not value.strip():
                raise CorpusError(f"{where}: {field} must be non-empty")

        if record["category"] not in CATEGORIES:
            raise CorpusError(
                f"{where}: unknown category {record['category']!r}"
            )

        rule = record["rule"]
        if "." not in rule:
            raise CorpusError(f"{where}: rule must be <operation>.<detail>")
        operation = rule.split(".", 1)[0]
        if operation not in OPERATIONS:
            raise CorpusError(f"{where}: unknown operation {operation!r} in rule")

        if record["id"] in seen_ids:
            raise CorpusError(f"{where}: duplicate id {record['id']!r}")
        seen_ids.add(record["id"])

        cases.append(record)

    return cases


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return load_cases()


def _write_corpus(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _valid_record(**overrides) -> dict:
    record = {
        "id": "example",
        "category": "order",
        "rule": "normalize.logical-order",
        "input": "कर्म",
        "expected": "कर्म",
        "source": "docs/devanagari.md",
        "notes": "example",
    }
    record.update(overrides)
    return record


# --- the real corpus -------------------------------------------------------

def test_corpus_is_well_formed(cases):
    assert cases


def test_at_least_50_cases(cases):
    assert len(cases) >= 50


def test_ids_are_unique(cases):
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_required_categories_are_covered(cases):
    covered = {case["category"] for case in cases}
    assert REQUIRED_CATEGORIES <= covered


def test_every_case_is_sourced_and_annotated(cases):
    for case in cases:
        assert case["source"].strip()
        assert case["notes"].strip()
        assert case["expected"].strip()


def test_invalid_cases_are_tagged_as_invalid(cases):
    for case in cases:
        if case["category"] == "invalid":
            assert case["rule"].startswith("invalid.")


def test_repo_sources_resolve_and_contain_the_input(cases):
    for case in cases:
        match = SOURCE_RE.match(case["source"])
        if match is None:
            continue

        path = ROOT / match.group("path")
        lineno = int(match.group("line"))
        assert path.is_file(), f"{case['id']}: missing source {path}"

        lines = path.read_text(encoding="utf-8").splitlines()
        assert 0 < lineno <= len(lines), f"{case['id']}: line {lineno} out of range"
        assert case["input"] in lines[lineno - 1], (
            f"{case['id']}: input not found in {case['source']}"
        )


def test_corpus_tests_do_not_import_parser_code():
    banned = (
        "redbook_parser",
        "water_parser",
        "migration_parser",
        "cidmap",
    )
    for path in HERE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in text, f"{path.name} imports {name}"
            assert f"from {name}" not in text, f"{path.name} imports {name}"


# --- malformed corpora must fail ------------------------------------------

def test_rejects_invalid_json(tmp_path):
    path = _write_corpus(tmp_path, ['{"id": "x"'])
    with pytest.raises(CorpusError, match="invalid JSON"):
        load_cases(path)


def test_rejects_missing_field(tmp_path):
    record = _valid_record()
    del record["notes"]
    path = _write_corpus(tmp_path, [json.dumps(record)])
    with pytest.raises(CorpusError, match="missing fields: notes"):
        load_cases(path)


def test_rejects_empty_expected(tmp_path):
    path = _write_corpus(tmp_path, [json.dumps(_valid_record(expected="   "))])
    with pytest.raises(CorpusError, match="expected must be non-empty"):
        load_cases(path)


def test_rejects_unknown_category(tmp_path):
    path = _write_corpus(tmp_path, [json.dumps(_valid_record(category="font"))])
    with pytest.raises(CorpusError, match="unknown category"):
        load_cases(path)


def test_rejects_unknown_operation(tmp_path):
    path = _write_corpus(tmp_path, [json.dumps(_valid_record(rule="transliterate.nukta"))])
    with pytest.raises(CorpusError, match="unknown operation"):
        load_cases(path)


def test_rejects_rule_without_operation(tmp_path):
    path = _write_corpus(tmp_path, [json.dumps(_valid_record(rule="nukta"))])
    with pytest.raises(CorpusError, match="operation"):
        load_cases(path)


def test_rejects_duplicate_ids(tmp_path):
    path = _write_corpus(
        tmp_path,
        [json.dumps(_valid_record()), json.dumps(_valid_record())],
    )
    with pytest.raises(CorpusError, match="duplicate id"):
        load_cases(path)


def test_rejects_non_string_field(tmp_path):
    path = _write_corpus(tmp_path, [json.dumps(_valid_record(notes=3))])
    with pytest.raises(CorpusError, match="notes must be a string"):
        load_cases(path)


def test_rejects_blank_line(tmp_path):
    path = _write_corpus(
        tmp_path, [json.dumps(_valid_record()), "", json.dumps(_valid_record(id="two"))]
    )
    with pytest.raises(CorpusError, match="blank line"):
        load_cases(path)


def test_rejects_empty_corpus(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(CorpusError, match="empty"):
        load_cases(path)
