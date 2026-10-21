"""Behaviour tests for kagaj_core.devanagari against the #4 corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kagaj_core.devanagari import (
    Issue,
    canonical_key,
    normalize,
    segment_aksaras,
    validate,
)

CASES_PATH = Path(__file__).with_name("cases.jsonl")
CASES = [
    json.loads(line)
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

INVALID_CODES = {
    "invalid.visual-order-matra": "leading-matra",
    "invalid.extra-nukta": "nukta-invalid-base",
    "invalid.nukta-after-virama": "nukta-after-virama",
    "invalid.nukta-after-matra": "nukta-after-matra",
    "invalid.nukta-on-vowel": "nukta-on-vowel",
    "invalid.double-virama": "double-virama",
    "invalid.leading-virama": "leading-virama",
    "invalid.leading-nukta": "leading-nukta",
    "invalid.matra-on-vowel": "matra-on-vowel",
    "invalid.double-nukta": "double-nukta",
    "invalid.leading-mark": "leading-mark",
    "invalid.control-character": "control-character",
    "invalid.orphan-zwj": "joiner-position",
    "invalid.orphan-zwnj": "joiner-position",
}


def _select(prefix: str) -> list[dict]:
    return [case for case in CASES if case["rule"].startswith(prefix)]


@pytest.mark.parametrize(
    "case", _select("normalize."), ids=lambda case: case["id"]
)
def test_normalize_matches_corpus(case):
    assert normalize(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_normalize_is_idempotent(case):
    once = normalize(case["input"])
    assert normalize(once) == once


@pytest.mark.parametrize(
    "case", _select("canonical_key."), ids=lambda case: case["id"]
)
def test_canonical_key_matches_corpus(case):
    drop_joiners = case["rule"] == "canonical_key.joiners-dropped"
    assert canonical_key(case["input"], drop_joiners=drop_joiners) == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("drop_joiners", [False, True])
def test_canonical_key_is_idempotent(case, drop_joiners):
    once = canonical_key(case["input"], drop_joiners=drop_joiners)
    assert canonical_key(once, drop_joiners=drop_joiners) == once


@pytest.mark.parametrize(
    "case", _select("segment."), ids=lambda case: case["id"]
)
def test_segment_aksaras_matches_corpus(case):
    assert segment_aksaras(case["input"]) == case["expected"].split("|")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_segment_aksaras_preserves_every_character(case):
    assert "".join(segment_aksaras(case["input"])) == case["input"]


@pytest.mark.parametrize(
    "case", _select("invalid."), ids=lambda case: case["id"]
)
def test_validate_flags_every_invalid_case(case):
    issues = validate(case["input"])
    expected_code = INVALID_CODES[case["rule"]]
    assert issues, f"no issue for {case['id']}"
    assert expected_code in {issue.code for issue in issues}


@pytest.mark.parametrize(
    "case", _select("repair."), ids=lambda case: case["id"]
)
def test_validate_accepts_structurally_valid_repair_cases(case):
    assert validate(case["input"]) == []


@pytest.mark.parametrize(
    "case",
    _select("normalize."),
    ids=lambda case: case["id"],
)
def test_validate_has_no_false_positives_on_valid_corpus(case):
    assert validate(case["input"]) == []


def test_validate_false_positive_regression_list():
    valid = [
        "स्वप्निल",
        "खड़ग बहादुर बस्याल",
        "नेपाल सरकार",
        "प्रतिनिधि सभा",
        "संघीय संसद",
        "हिन्दी",
        "काठमाडौं",
        "विद्यालय",
        "राष्ट्रिय",
        "श्रीमती",
        "अयोध्या प्रसाद यादव",
        "दुईमत",
        "क्‍ष",
        "क्‌ष",
        "हेा",
        "संविधान",
    ]
    for text in valid:
        assert validate(text) == [], text


def test_validate_detects_virama_on_independent_vowel():
    codes = {issue.code for issue in validate("अ्")}
    assert "virama-on-vowel" in codes


def test_validate_detects_matra_on_matra():
    codes = {issue.code for issue in validate("किा")}
    assert "matra-on-matra" in codes


def test_validate_accepts_split_two_part_matra():
    assert validate("हेा") == []


def test_validate_accepts_precomposed_nukta_consonant_cluster():
    assert validate("\u0958\u094d\u0937") == []


def test_segment_accepts_precomposed_nukta_consonant_cluster():
    assert segment_aksaras("\u0958\u094d\u0937") == ["\u0958\u094d\u0937"]


def test_validate_reports_spans():
    issues = validate("का़")
    assert issues
    assert all(isinstance(issue, Issue) for issue in issues)
    assert issues[0].start == 2
    assert issues[0].end == 3


def test_segment_hindi_acceptance_case():
    assert segment_aksaras("हिन्दी") == ["हि", "न्दी"]


@pytest.mark.parametrize(
    "case",
    [case for case in CASES if case["category"] == "valid-word"],
    ids=lambda case: case["id"],
)
def test_valid_words_survive_normalize_and_canonical_key(case):
    assert normalize(case["input"]) == case["input"]
    assert canonical_key(case["input"]) == case["input"]


def test_canonical_key_folds_digits_whitespace_and_danda():
    assert canonical_key("२०८३") == "2083"
    assert canonical_key("नेपाल   सरकार") == "नेपाल सरकार"
    assert canonical_key("सरकार ।   नेपाल") == "सरकार। नेपाल"
    assert canonical_key("सरकार।नेपाल") == "सरकार। नेपाल"


def test_canonical_key_joiners_are_optional():
    assert canonical_key("क्‍ष") == "क्‍ष"
    assert canonical_key("क्‍ष", drop_joiners=True) == "क्ष"
    assert canonical_key("क्‌ष", drop_joiners=True) == "क्ष"


def test_canonical_key_does_not_reorder_visual_text():
    assert canonical_key("िक") == "िक"
    assert canonical_key("कि") == "कि"


def test_normalize_preserves_joiners_digits_and_punctuation():
    text = "क्‍ष २०८३।"
    assert normalize(text) == text


def test_normalize_does_not_fold_digits():
    assert normalize("२०८३") == "२०८३"


def test_normalize_composes_excluded_nukta_letters():
    assert normalize("\u0958") == "\u0915\u093c"
    assert normalize("\u095c") == "\u0921\u093c"
