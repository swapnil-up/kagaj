"""Tests for the new-versus-reentry pattern module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import patterns_reentry as pr
from migration_parser.research.datasets import (
    country_channel_year,
    load_panel,
)
from migration_parser.research.patterns_gender_channel import CHANNELS


@pytest.fixture(scope="module")
def report():
    return pr.build()


@pytest.fixture(scope="module")
def panel():
    return load_panel(safe=True)


def test_build_has_required_keys(report):
    assert set(report) >= {
        "meta", "annual", "comparable_window", "country_base_latest",
        "top_destinations", "decomposition", "reentry_orientation",
        "association", "robustness",
    }
    meta = report["meta"]
    assert meta["base_fy"] == pr.BASE_FY
    assert meta["latest_fy"] == pr.LATEST_FY
    assert meta["partial_fy"] == pr.PARTIAL_FY
    assert meta["partial_fy_excluded"] is True
    assert meta["comparable_fy"] == pr.COMPARABLE_FY
    assert meta["min_latest_count"] == pr.MIN_LATEST
    assert meta["channels"] == list(CHANNELS)
    assert meta["fiscal_years"]
    assert meta["caveats"]


def test_annual_counts_reconcile_to_channel_totals(report, panel):
    cc = country_channel_year(panel)
    grouped = cc.groupby(["fiscal_year", "channel_canonical"])["count"].sum()
    annual = {row["fiscal_year"]: row for row in report["annual"]}
    for fy, row in annual.items():
        assert sum(row["channels"].values()) == row["total"]
        assert (row["individual_new"] + row["individual_reentry"]
                + row["other_channels"]) == row["total"]
        assert row["individual_total"] == (
            row["individual_new"] + row["individual_reentry"])
        for channel, value in row["channels"].items():
            assert value == int(grouped.get((fy, channel), 0))
        assert row["total"] == int(grouped.loc[fy].sum())


def test_annual_coverage_flags_follow_reported_channels(report, panel):
    cc = country_channel_year(panel)
    reported = cc.groupby("fiscal_year")["channel_canonical"].apply(set).to_dict()
    for row in report["annual"]:
        fy = row["fiscal_year"]
        assert row["new_reported"] == (pr.NEW in reported[fy])
        assert row["reentry_reported"] == (pr.REENTRY in reported[fy])
        assert set(row["reported_channels"]) == reported[fy]
        if not row["new_reported"]:
            assert row["new_share_pct"] is None
            assert row["new_to_reentry_ratio"] is None
            assert row["notes"]


def test_partial_fiscal_year_is_absent_from_trends(report):
    assert pr.PARTIAL_FY not in report["meta"]["fiscal_years"]
    assert pr.PARTIAL_FY not in [row["fiscal_year"] for row in report["annual"]]
    assert pr.PARTIAL_FY not in report["top_destinations"]["years"]
    assert report["annual"][-1]["fiscal_year"] == pr.LATEST_FY
    for row in report["reentry_orientation"]["stability"]:
        assert row["from"] != pr.PARTIAL_FY
        assert row["to"] != pr.PARTIAL_FY
    assert report["decomposition"]["latest_fiscal_year"] == pr.LATEST_FY
    assert report["comparable_window"]["end_fiscal_year"] == pr.LATEST_FY
    assert pr.PARTIAL_FY not in json.dumps(report["decomposition"])
    assert pr.PARTIAL_FY not in json.dumps(report["top_destinations"])


def test_comparable_window_has_coverage_notes(report):
    block = report["comparable_window"]
    assert block["available"] is True
    assert block["start_fiscal_year"] == pr.COMPARABLE_FY
    assert block["end_fiscal_year"] == pr.LATEST_FY
    assert block["coverage"]["same_channel_set"] is True
    assert block["coverage"]["individual_new_separately_reported_at_start"] is True
    assert "2081/82" in block["note"]
    assert block["caveat"] == pr.CAVEAT
    annual = {row["fiscal_year"]: row for row in report["annual"]}
    assert annual[pr.COMPARABLE_FY]["new_reported"] is True
    assert annual[pr.LATEST_FY]["same_channel_set_as_previous"] is True


def test_country_base_latest_respects_threshold_and_shares(report):
    block = report["country_base_latest"]
    assert block["destinations"]
    assert all(row["latest_total"] >= pr.MIN_LATEST
               for row in block["destinations"])
    for row in block["destinations"]:
        for key in ("new_share_latest_pct", "new_share_base_pct",
                    "reentry_share_latest_pct", "reentry_share_base_pct"):
            value = row[key]
            if value is not None:
                assert 0.0 <= value <= 100.0
        assert row["latest_individual_new"] >= 0
        assert row["latest_individual_reentry"] >= 0
        assert row["latest_total"] == (
            row["latest_individual_new"] + row["latest_individual_reentry"]
            + row["latest_other_channels"])
        assert row["latest_female"] >= 0
        assert row["latest_male"] >= 0


def test_top_destinations_series_are_valid(report):
    block = report["top_destinations"]
    assert len(block["destinations"]) <= pr.TOP_DESTINATIONS
    assert block["years"] == [row["fiscal_year"] for row in report["annual"]]
    for destination in block["destinations"]:
        assert len(destination["series"]) == len(block["years"])
        for point in destination["series"]:
            assert point["individual_new"] >= 0
            assert point["individual_reentry"] >= 0
            assert point["total"] >= (
                point["individual_new"] + point["individual_reentry"])
            for key in ("new_share_pct", "reentry_share_pct"):
                value = point[key]
                if value is not None:
                    assert 0.0 <= value <= 100.0


def test_decomposition_is_internally_consistent(report):
    decomposition = report["decomposition"]
    for block in (decomposition["base_to_latest"],
                  decomposition["comparable_window"]):
        assert block["sums_correctly"] is True
        assert (sum(row["change"] for row in block["channels"])
                == block["total_change"])
        assert block["end_total"] - block["start_total"] == block["total_change"]
    for key in ("base_to_latest_split", "comparable_window_split"):
        split = decomposition[key]
        assert split["sums_correctly"] is True
        assert (split["individual_new_change"]
                + split["individual_reentry_change"]
                + split["other_channels_change"]) == split["total_change"]
    for name, block in decomposition["country_contributors"].items():
        assert block["sums_correctly"] is True, name
        assert all(row["change"] > 0 for row in block["top_positive"])
        assert all(row["change"] < 0 for row in block["top_negative"])


def test_reentry_orientation_distribution_and_stability(report):
    block = report["reentry_orientation"]
    distribution = block["distribution"]
    assert distribution["n"] > 0
    for key in ("mean_pct", "weighted_mean_pct", "min_pct", "max_pct",
                "median_pct", "p25_pct", "p75_pct"):
        assert distribution[key] is not None
        assert 0.0 <= distribution[key] <= 100.0
    assert block["highest_reentry_share"]
    assert block["lowest_reentry_share"]
    for row in block["destinations"]:
        assert row["latest_total"] >= pr.MIN_LATEST
        assert 0.0 <= row["reentry_share_pct"] <= 100.0
    for row in block["stability"]:
        assert row["n_common_above_min"] >= 0
        if row["spearman"] is not None:
            assert -1.0 <= row["spearman"] <= 1.0


def test_association_is_labelled_descriptive(report):
    block = report["association"]
    assert "descriptive" in block["label"]
    assert "not causal" in block["label"]
    for key in ("total_growth_vs_latest_reentry_share",
                "new_growth_vs_latest_reentry_share"):
        corr = block[key]
        assert corr["n"] >= 0
        if corr["pearson"] is not None:
            assert -1.0 <= corr["pearson"] <= 1.0
        if corr["spearman"] is not None:
            assert -1.0 <= corr["spearman"] <= 1.0


def test_robustness_thresholds_and_denominator(report):
    block = report["robustness"]
    thresholds = block["alternative_thresholds"]["thresholds"]
    assert [row["threshold"] for row in thresholds] == list(pr.THRESHOLD_OPTIONS)
    assert all(row["n_countries"] >= 0 for row in thresholds)
    restricted = block["exclude_non_individual_channels"]
    for key in ("base_reentry_share_of_individual_pct",
                "comparable_reentry_share_of_individual_pct",
                "latest_reentry_share_of_individual_pct"):
        assert restricted[key] is not None
        assert 0.0 <= restricted[key] <= 100.0
    assert pr.CAVEAT in restricted["note"] or "composition effect" in restricted["note"]


def test_reentry_caveat_is_repeated(report):
    assert "not a unique-person return history" in report["meta"]["caveat"]
    assert "not a unique-person return history" in report["decomposition"]["caveat"]
    assert "not a unique-person return history" in report["reentry_orientation"]["caveat"]
    assert "not a unique-person return history" in report["association"]["caveat"]
    assert "not a unique-person return history" in report["robustness"]["caveat"]


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, value


def test_public_outputs_have_no_nan_or_inf(report):
    for path, value in _walk(report):
        if isinstance(value, float):
            assert math.isfinite(value), path
    encoded = json.dumps(report, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded["meta"]["base_fy"] == pr.BASE_FY
    assert decoded["decomposition"]["base_to_latest_split"]["sums_correctly"]
