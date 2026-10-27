"""Tests for the gender and channel pattern module."""

import json

import pytest

pytest.importorskip("pandas")

from migration_parser.research import patterns_gender_channel as pgc
from migration_parser.research.datasets import (
    country_gender_year,
    country_year,
    load_panel,
)


@pytest.fixture(scope="module")
def report():
    return pgc.build()


def test_meta_describes_safe_basis(report):
    panel = load_panel(safe=True)
    meta = report["meta"]
    assert meta["safe_rows"] == len(panel)
    assert meta["safe_documents"] == panel["doc_id"].nunique()
    assert meta["base_fy"] == pgc.BASE_FY
    assert meta["latest_fy"] == pgc.LATEST_FY
    assert meta["partial_fy"] == pgc.PARTIAL_FY
    assert meta["partial_fy_excluded"] is True
    assert meta["min_destination_count"] == pgc.MIN_DESTINATION
    assert meta["caveats"]


def test_partial_fiscal_year_is_excluded(report):
    years = [row["fiscal_year"] for row in report["annual"]]
    assert pgc.PARTIAL_FY not in years
    assert report["annual"][-1]["fiscal_year"] == pgc.LATEST_FY
    for block in (
        report["female_growth_divergence"],
        report["female_shift_share"],
        report["female_by_channel"],
        report["channel_composition_by_destination"],
        report["channel_growth"],
        report["reentry_by_destination"],
    ):
        assert pgc.PARTIAL_FY not in json.dumps(block)


def test_channel_and_gender_totals_reconcile(report):
    annual = {row["fiscal_year"]: row for row in report["annual"]}
    latest = annual[pgc.LATEST_FY]
    assert latest["female"] + latest["male"] == latest["total"]
    assert sum(latest["channels"].values()) == latest["total"]

    cy = country_year()
    cg = country_gender_year()
    safe_total = int(cy.loc[cy["fiscal_year"] == pgc.LATEST_FY, "count"].sum())
    gender_total = int(cg.loc[cg["fiscal_year"] == pgc.LATEST_FY, "count"].sum())
    assert latest["total"] == safe_total
    assert latest["female"] + latest["male"] == gender_total

    channel_rows = report["channel_growth"]["components"]["channels"]
    assert sum(row["latest_count"] for row in channel_rows) == safe_total


def test_channel_contribution_sums_to_total_growth(report):
    block = report["channel_growth"]["components"]
    contributions = [row["contribution_to_total_growth_pct"]
                     for row in block["channels"]
                     if row["contribution_to_total_growth_pct"] is not None]
    assert abs(sum(contributions) - 100.0) < 0.1
    changes = sum(row["change"] for row in block["channels"])
    assert changes == block["total_growth"]


def test_shift_share_components_sum_to_aggregate_change(report):
    block = report["female_shift_share"]
    component_sum = (
        block["within_destination_pp"]
        + block["destination_composition_pp"]
        + block["interaction_residual_pp"]
    )
    assert abs(component_sum - block["aggregate_change_pp"]) < 1e-6
    assert abs(component_sum - block["components_sum_pp"]) < 1e-6
    assert abs(block["interaction_check_pp"]
               - block["interaction_residual_pp"]) < 1e-6
    assert abs(
        block["latest_female_share_pct"]
        - block["base_female_share_pct"]
        - block["aggregate_change_pp"]
    ) < 1e-6


def _all_shares(report):
    for row in report["annual"]:
        yield row["female_share_pct"]
        yield from row["channel_shares_pct"].values()
    div = report["female_growth_divergence"]
    yield div["overall"]["base"]["female_share_pct"]
    yield div["overall"]["latest"]["female_share_pct"]
    for row in div["destinations"]:
        yield row["female_share_base_pct"]
        yield row["female_share_latest_pct"]
    for row in report["female_share_by_destination"]:
        yield row["latest_female_share_pct"]
        if row["base_female_share_pct"] is not None:
            yield row["base_female_share_pct"]
    for row in report["female_by_channel"]["channels"]:
        yield row["latest_female_share_pct"]
        if row["base_female_share_pct"] is not None:
            yield row["base_female_share_pct"]
    for row in report["channel_composition_by_destination"]["top_destinations"]:
        yield from (c["share_pct"] for c in row["channels"].values())
    for row in report["reentry_by_destination"]["destinations"]:
        yield row["latest_reentry_share_pct"]
        if row["base_reentry_share_pct"] is not None:
            yield row["base_reentry_share_pct"]


def test_shares_are_bounded(report):
    for share in _all_shares(report):
        assert share is not None
        assert 0.0 <= share <= 100.0


def test_female_growth_divergence_is_populated(report):
    block = report["female_growth_divergence"]
    overall = block["overall"]
    assert overall["female_growth_pct"] > overall["male_growth_pct"]
    assert overall["female_share_change_pp"] > 0
    assert block["destinations"]
    assert all(row["latest_total"] >= pgc.MIN_DESTINATION
               for row in block["destinations"])


def test_channel_dependence_lists_are_populated(report):
    block = report["channel_composition_by_destination"]
    assert block["top_destinations"]
    assert block["agency_dependent"]
    assert block["g2g_dependent"]
    assert all(row["agency_share_pct"] >= pgc.DEPENDENCE_PCT
               for row in block["agency_dependent"])
    assert all(row["g2g_share_pct"] >= pgc.DEPENDENCE_PCT
               for row in block["g2g_dependent"])


def test_reentry_is_labelled_as_a_channel(report):
    block = report["reentry_by_destination"]
    assert block["destinations"]
    assert block["top_volume"]
    assert "not an individual" in block["caveat"]
    top = block["top_volume"][0]
    assert top["latest_reentry"] <= top["latest_total"]


def test_report_is_json_serializable(report):
    encoded = json.dumps(report, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded["meta"]["base_fy"] == pgc.BASE_FY
    assert decoded["female_shift_share"]["aggregate_change_pp"] is not None
