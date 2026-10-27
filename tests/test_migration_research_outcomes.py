"""Tests for explicit outcome denominators and coverage accounting."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import patterns_outcomes as po


@pytest.fixture(scope="module")
def report():
    return po.build()


def _walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def test_build_has_required_keys(report):
    assert set(report) >= {
        "meta", "coverage", "gap_fill", "legacy_channel_review",
        "country_growth", "suspect_series", "annual_monthly_reconciliation",
    }
    assert report["meta"]["base_fy"] == po.BASE_FY
    assert report["meta"]["latest_fy"] == po.LATEST_FY
    assert report["meta"]["partial_fy"] == po.PARTIAL_FY
    assert set(report["meta"]["definitions"]) == {
        "total_verified", "deployment_verified", "reviewed_channels",
        "modern_consistent",
    }


def test_coverage_denominators_are_internally_consistent(report):
    rows = report["coverage"]["rows"]
    assert rows
    for row in rows:
        assert row["total_verified"] == (
            row["deployment_verified"] + row["legalization"])
        assert 0 <= row["reviewed_channels"] <= row["total_verified"]
        assert row["reviewed_share_of_total_pct"] is not None
        assert 0 <= row["reviewed_share_of_total_pct"] <= 100
        assert row["documents"] == (
            row["annual_documents"] + row["monthly_documents"])
        if row["partial"]:
            assert row["fiscal_year"] == po.PARTIAL_FY
        if not row["modern_complete"]:
            assert row["modern_consistent"] is None


def test_coverage_documents_are_unique_ids(report):
    rows = {r["fiscal_year"]: r for r in report["coverage"]["rows"]}
    assert rows["2082/83"]["annual_documents"] == 1
    assert rows["2082/83"]["monthly_documents"] == 12
    assert rows["2081/82"]["monthly_documents"] == 3
    assert rows["2083/84"]["monthly_documents"] == 2
    assert rows["2079/80"]["documents"] == 1


def test_gap_fill_is_flagged_and_balanced(report):
    gap = report["gap_fill"]
    assert gap["fiscal_year"] == "2075/76"
    assert gap["documents"] == ["report2020_annex_X"]
    assert gap["status"] == "unverified_gap_fill"
    assert gap["total_unverified"] == (
        gap["deployment_unverified"] + gap["legalization"])
    assert gap["new_entry"] == 0
    assert gap["total_from_male_female"] == (
        gap["total_unverified"] + gap["gender_total_difference"])
    assert gap["known_arithmetic_errors"] == 2


def test_legacy_channel_policy_is_explicit(report):
    policy = report["legacy_channel_review"]
    assert policy["new_entry"]["decision"] == "include in deployment_verified"
    assert policy["legalization"]["decision"] == "keep as a separate policy series"
    assert policy["new_entry"]["channel_comparable"] is False
    assert policy["legalization"]["channel_comparable"] is False


def test_country_growth_has_base_and_latest_counts(report):
    rows = report["country_growth"]
    assert rows
    names = {r["country"] for r in rows}
    assert {"Portugal", "South Korea", "United Arab Emirates"} <= names
    for row in rows:
        assert row["latest_total_verified"] >= po.SMALL_BASE
        assert row["base_deployment_verified"] >= 0
        assert row["latest_deployment_verified"] >= 0
        if row["base_deployment_verified"] > 0:
            assert row["deployment_growth_pct"] is not None
        assert row["base_reviewed_share_pct"] is None or (
            0 <= row["base_reviewed_share_pct"] <= 100)


def test_portugal_matches_source_and_is_flagged(report):
    row = next(r for r in report["country_growth"] if r["country"] == "Portugal")
    assert row["base_total_verified"] == 732
    assert row["base_deployment_verified"] == 732
    assert row["base_reviewed_channels"] == 2
    assert row["latest_total_verified"] == 3800
    assert row["latest_deployment_verified"] == 3800
    assert row["deployment_growth_pct"] == pytest.approx(419.1257)
    assert row["reviewed_growth_pct"] == pytest.approx(189900.0)
    assert row["small_base"] is True
    flagged = {r["country"]: r for r in report["suspect_series"]["rows"]}
    assert "Portugal" in flagged
    assert flagged["Portugal"]["base_reviewed_share_pct"] < 1


def test_suspect_series_flags_small_bases_or_sign_flips(report):
    block = report["suspect_series"]
    assert block["n_flagged"] == len(block["rows"])
    for row in block["rows"]:
        gap = row["reviewed_minus_deployment_growth_pp"]
        assert (row["small_base"] or row["sign_flip"]
                or (gap is not None and abs(gap) >= block["threshold_growth_pp"]))


def test_annual_monthly_reconciliation(report):
    block = report["annual_monthly_reconciliation"]
    assert block["fiscal_year"] == po.LATEST_FY
    assert block["pairs"] == block["exact_pairs"] + block["mismatched_pairs"]
    assert block["exact_pairs"] > 700
    assert block["mismatched_pairs"] == len(block["mismatches"])
    assert block["total_abs_difference"] < 100
    for row in block["mismatches"]:
        assert row["difference"] == row["annual"] - row["monthly"]
        assert row["difference"] != 0


def test_no_nan_or_infinity_in_public_output(report):
    text = json.dumps(report)
    assert "NaN" not in text
    assert "Infinity" not in text
    for value in _walk(report):
        if isinstance(value, float):
            assert math.isfinite(value)
