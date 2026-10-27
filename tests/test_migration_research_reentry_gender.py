"""Tests for the re-entry by gender intersection module."""

import json
import math

import pytest

pytest.importorskip("pandas")

from migration_parser.research import patterns_reentry_gender as prg
from migration_parser.research.datasets import (
    country_gender_year,
    load_panel,
)
from migration_parser.research.patterns_gender_channel import (
    _gender_channel_year,
)


@pytest.fixture(scope="module")
def report():
    return prg.build()


def _walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)
    else:
        yield value


def test_required_top_level_keys(report):
    for key in (
        "meta",
        "definitions",
        "caveats",
        "annual",
        "latest_summary",
        "country_table",
        "decomposition",
        "growth_decomposition",
        "trajectories",
        "orientation",
        "robustness",
    ):
        assert key in report
    assert report["meta"]["partial_fy_excluded"] is True
    assert report["meta"]["source"].endswith("_gender_channel_year")


def test_meta_describes_safe_basis(report):
    panel = load_panel(safe=True)
    meta = report["meta"]
    assert meta["safe_rows"] == len(panel)
    assert meta["safe_documents"] == panel["doc_id"].nunique()
    assert meta["base_fy"] == prg.BASE_FY
    assert meta["latest_fy"] == prg.LATEST_FY
    assert meta["comparable_base_fy"] == prg.COMPARABLE_BASE_FY
    assert meta["partial_fy"] == prg.PARTIAL_FY
    assert meta["min_volume"] == prg.MIN_VOLUME
    assert report["caveats"]


def test_sex_channel_rows_reconcile_to_gender_totals(report):
    panel = load_panel(safe=True)
    gc = _gender_channel_year(panel)
    cg = country_gender_year(panel)
    annual = {row["fiscal_year"]: row for row in report["annual"]}
    for fy in annual:
        expected = cg[cg["fiscal_year"] == fy].groupby("gender")["count"].sum()
        observed = gc[gc["fiscal_year"] == fy].groupby("gender")["count"].sum()
        assert int(expected.get("female", 0)) == int(observed.get("female", 0))
        assert int(expected.get("male", 0)) == int(observed.get("male", 0))
        assert annual[fy]["female"] == int(expected.get("female", 0))
        assert annual[fy]["male"] == int(expected.get("male", 0))
        assert annual[fy]["female"] + annual[fy]["male"] == annual[fy]["total"]
        reported = annual[fy]["channels_reported"]
        assert sum(annual[fy]["channels"][c]["female"] for c in reported) \
            == annual[fy]["female"]


def test_partial_fiscal_year_is_excluded(report):
    assert all(row["fiscal_year"] != prg.PARTIAL_FY
               for row in report["annual"])
    assert report["annual"][-1]["fiscal_year"] == prg.LATEST_FY
    for block in (
        report["country_table"],
        report["decomposition"],
        report["growth_decomposition"],
        report["trajectories"],
        report["orientation"],
        report["robustness"],
    ):
        assert prg.PARTIAL_FY not in json.dumps(block)


def test_country_threshold_and_shares_are_valid(report):
    block = report["country_table"]
    assert block["destinations"]
    assert block["min_volume"] == prg.MIN_VOLUME
    for row in block["destinations"]:
        assert row["latest_total"] >= prg.MIN_VOLUME
        for key in (
            "latest_female_share_pct",
            "new_female_share_pct",
            "reentry_female_share_pct",
            "reentry_share_of_focus_pct",
        ):
            value = row[key]
            if value is not None:
                assert 0.0 <= value <= 100.0
        if row["new_to_reentry_female_gap_pp"] is not None:
            assert -100.0 <= row["new_to_reentry_female_gap_pp"] <= 100.0
        assert row["new_female"] + row["new_male"] == row["new_total"]
        assert row["reentry_female"] + row["reentry_male"] == row["reentry_total"]


def test_gap_handles_missing_and_zero_safely(report):
    for row in report["country_table"]["destinations"]:
        if row["new_total"] == 0 or row["reentry_total"] == 0:
            assert row["orientation"] == "insufficient"
            assert row["new_to_reentry_female_gap_pp"] is None
        else:
            expected = (row["new_female_share_pct"]
                        - row["reentry_female_share_pct"])
            assert abs(row["new_to_reentry_female_gap_pp"]
                       - round(expected, 2)) < 0.02


@pytest.mark.parametrize(
    "block_name",
    ["comparable_window", "base_to_latest"],
)
def test_decomposition_components_sum_internally(report, block_name):
    block = report["decomposition"][block_name]
    decompositions = [
        value for key, value in block.items()
        if isinstance(value, dict) and "aggregate_change_pp" in value
    ]
    assert decompositions
    for decomposition in decompositions:
        within = decomposition["within_channel_pp"]
        composition = decomposition["channel_composition_pp"]
        interaction = decomposition["interaction_residual_pp"]
        component_sum = within + composition + interaction
        assert abs(component_sum - decomposition["components_sum_pp"]) < 1e-5
        assert abs(component_sum
                   - decomposition["aggregate_change_pp"]) < 1e-5
        contributions = [row["total_contribution_pp"]
                         for row in decomposition["channel_contributions"]]
        assert abs(sum(contributions) - component_sum) < 1e-5


def test_growth_decomposition_contributions_are_populated(report):
    growth = report["growth_decomposition"]["comparable_window"]
    assert growth["aggregate"]["female_change"] is not None
    assert growth["new_female_contribution_pct"] is not None
    assert growth["reentry_female_contribution_pct"] is not None
    contributions = [row["female_change_contribution_pct"]
                     for row in growth["channels_detail"]
                     if row["female_change_contribution_pct"] is not None]
    assert abs(sum(contributions) - 100.0) < 0.1
    positive = [row["positive_female_change_contribution_pct"]
                for row in growth["channels_detail"]
                if row["positive_female_change_contribution_pct"] is not None]
    assert abs(sum(positive) - 100.0) < 0.1


def test_robustness_variants_present(report):
    block = report["robustness"]
    assert len(block["thresholds"]) == len(prg.ALT_THRESHOLDS)
    assert {row["min_volume"] for row in block["thresholds"]} \
        == set(prg.ALT_THRESHOLDS)
    assert block["comparable_window"]["start_fiscal_year"] \
        == prg.COMPARABLE_BASE_FY
    assert "four_channel_decomposition" in block["comparable_window"]
    assert "new_reentry_decomposition" in block["comparable_window"]
    assert block["exclude_g2g_agency"]["latest"]["total"] > 0
    assert block["only_channels_reported_in_both_years"]["channels"] \
        == list(prg.BASE_TO_LATEST_CHANNELS)
    assert "decomposition" in block["all_four_missing_as_zero"]
    for row in block["thresholds"]:
        assert row["n_countries"] > 0


def test_orientation_lists_and_rank_stability(report):
    block = report["orientation"]
    assert block["gap_distribution"]["n_countries"] > 0
    assert block["rank_stability"]
    for row in block["rank_stability"]:
        assert row["n_common_countries"] >= 3
        if row["spearman_gap"] is not None:
            assert -1.0 <= row["spearman_gap"] <= 1.0
    for row in block["reentry_heavy_and_female_heavy"]:
        assert row["reentry_share_of_focus_pct"] >= prg.REENTRY_HEAVY_PCT
    for row in block["new_more_female"]:
        assert row["gap_pp"] >= prg.ORIENTATION_GAP_PP
    for row in block["reentry_more_female"]:
        assert row["gap_pp"] <= -prg.ORIENTATION_GAP_PP


def test_trajectories_cover_top_destinations(report):
    block = report["trajectories"]
    assert block
    assert len(block) <= prg.TOP_DESTINATIONS
    complete = report["meta"]["complete_fiscal_years"]
    for country in block:
        assert [point["fiscal_year"] for point in country["points"]] == complete
        for point in country["points"]:
            if not point["new_reported"]:
                assert point["new_female_share_pct"] is None
            if not point["reentry_reported"]:
                assert point["reentry_female_share_pct"] is None


def test_public_outputs_have_no_nan_or_inf(report):
    for value in _walk(report):
        if isinstance(value, float):
            assert math.isfinite(value)
    encoded = json.dumps(report, allow_nan=False)
    assert json.loads(encoded)["meta"]["latest_fy"] == prg.LATEST_FY
