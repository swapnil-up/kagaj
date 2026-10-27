"""Tests for the Phase 1 migration robustness/sensitivity module."""

import json

import pandas as pd
import pytest

pytest.importorskip("pandas")

from migration_parser.research import audit, datasets, patterns_robustness as rob


@pytest.fixture(scope="module")
def report():
    return rob.build()


def test_build_is_json_serializable_and_has_expected_sections(report):
    payload = json.dumps(report)
    roundtrip = json.loads(payload)
    assert roundtrip["generated_at"] == report["generated_at"]
    assert {
        "meta", "safe_vs_permissive", "annual_monthly", "basis_sensitivity",
        "archive_scope", "leave_one_doc_out", "series_dedupe",
    }.issubset(report)
    assert report["meta"]["limitations"]
    assert report["meta"]["thresholds"]["complete_months"] == 12


def test_safe_permissive_comparison_reconciles(report):
    section = report["safe_vs_permissive"]
    safe = section["safe"]
    permissive = section["permissive"]
    reconciliation = section["reconciliation"]
    assert section["permissive_is_superset"] is True
    assert permissive["rows"] >= safe["rows"]
    assert permissive["documents"] >= safe["documents"]
    assert reconciliation["safe_rows_plus_extra_rows_equals_permissive_rows"]
    assert reconciliation["extra_rows"] == permissive["rows"] - safe["rows"]
    assert reconciliation["extra_rows"] > 0
    for fy, delta in section["delta_permissive_minus_safe"][
            "annual_total_by_fiscal_year"].items():
        assert delta >= 0, fy
    delta_shares = section["delta_permissive_minus_safe"][
        "annual_total_share_of_safe_pct"]
    assert max(v for v in delta_shares.values() if v is not None) > 0
    assert section["top5_rank_changes"]["latest_fy"] == rob.LATEST_FY


def test_annual_monthly_gaps_match_audit_logic(report):
    safe = datasets.load_panel(safe=True)
    expected = {row["fiscal_year"]: row
                for row in audit._annual_monthly_gaps(safe)}
    got = {row["fiscal_year"]: row
           for row in report["annual_monthly"]["rows"]}
    assert set(got) == set(expected)
    for fy, row in got.items():
        for key in ("annual", "monthly_sum", "month_docs", "gap_pct",
                    "complete_monthly", "within_tolerance"):
            assert row[key] == expected[fy][key], (fy, key)
    assert got["2082/83"]["validation"] == "validated"
    assert got["2081/82"]["validation"] == "not_validated_incomplete_monthly"


def test_basis_sensitivity_flags_partial_years(report):
    rows = {row["fiscal_year"]: row
            for row in report["basis_sensitivity"]["rows"]}
    assert rows["2082/83"]["complete_monthly"] is True
    assert rows["2082/83"]["partial"] is False
    assert rows["2081/82"]["partial"] is True
    assert rows["2081/82"]["gap_pct"] > 1
    assert "2083/84" not in rows
    assert rows["2082/83"]["top_annual"] == rows["2082/83"]["top_month"]
    assert (rows["2082/83"]["total_absolute_country_difference"]
            <= rows["2082/83"]["annual_total"] * 0.001)


def _archive_frame():
    return pd.DataFrame([
        {"period_bs": "2071 Baishakh", "scope": "month", "section": "country",
         "row_type": "detail", "gender": "total", "count": 100, "doc_id": "a"},
        {"period_bs": "2071 Baishakh", "scope": "final_approved",
         "section": "country", "row_type": "detail", "gender": "total",
         "count": 120, "doc_id": "a"},
        {"period_bs": "2071 Jestha", "scope": "month", "section": "country",
         "row_type": "detail", "gender": "total", "count": 80, "doc_id": "b"},
        {"period_bs": "2071 Asar", "scope": "final_approved", "section": "country",
         "row_type": "detail", "gender": "total", "count": 90, "doc_id": "c"},
        {"period_bs": "2071 Shrawan", "scope": "month", "section": "country",
         "row_type": "detail", "gender": "total", "count": 50, "doc_id": "d"},
        {"period_bs": "2071 Shrawan", "scope": "cumulative", "section": "country",
         "row_type": "detail", "gender": "total", "count": 500, "doc_id": "d"},
    ])


def test_archive_scope_rule_is_deterministic():
    first = rob._scope_sensitivity(_archive_frame())
    second = rob._scope_sensitivity(_archive_frame())
    assert first == second
    by_period = {row["period_bs"]: row for row in first["by_period"]}
    assert by_period["2071 Baishakh"]["chosen_scope"] == "final_approved"
    assert by_period["2071 Jestha"]["chosen_scope"] == "month"
    assert by_period["2071 Asar"]["chosen_scope"] == "final_approved"
    assert by_period["2071 Shrawan"]["chosen_scope"] == "month"
    assert first["periods_with_both_month_and_final"] == 1
    assert first["scope_choice_matters"] == ["2071 Baishakh"]
    assert first["unique_scope_sets"]["cumulative+month"] == 1


def test_real_archive_scope_never_sums_peer_scopes(report):
    rows = report["archive_scope"]["by_period"]
    assert rows == sorted(rows, key=lambda r: rob._period_key(r["period_bs"]))
    for row in rows:
        if "final_approved" in row["scopes"]:
            assert row["chosen_scope"] == "final_approved"
        elif "month" in row["scopes"]:
            assert row["chosen_scope"] == "month"
        else:
            assert row["chosen_scope"] is None
        assert row["month_final_overlap"] is False


def test_leave_one_document_out_recomputes_on_synthetic_frame():
    frame = pd.DataFrame([
        {"name_canonical": "A", "doc_id": "d1", "count": 10},
        {"name_canonical": "B", "doc_id": "d1", "count": 0},
        {"name_canonical": "A", "doc_id": "d2", "count": 30},
        {"name_canonical": "B", "doc_id": "d2", "count": 60},
    ])
    result = rob._leave_one_doc_out(frame)
    assert result["full_total"] == 100
    assert result["full_hhi"] == pytest.approx(0.52)
    docs = {row["doc_id"]: row for row in result["by_document"]}
    assert docs["d1"]["total_without_doc"] == 90
    assert docs["d1"]["hhi_without_doc"] == pytest.approx(
        (30 / 90) ** 2 + (60 / 90) ** 2, abs=1e-6)
    assert docs["d2"]["total_without_doc"] == 10
    assert docs["d2"]["hhi_without_doc"] == pytest.approx(1.0)
    assert result["summary"]["range_delta_total"] == 80


def test_complete_year_lodo_matches_monthly_sum(report):
    lodo = {row["fiscal_year"]: row
            for row in report["leave_one_doc_out"]["by_fiscal_year"]}
    monthly = {row["fiscal_year"]: row
               for row in report["annual_monthly"]["rows"]}
    complete = lodo["2082/83"]
    assert complete["basis"] == "monthly"
    assert complete["complete"] is True
    assert complete["documents"] == 12
    assert complete["full_total"] == monthly["2082/83"]["monthly_sum"]
    assert complete["summary"]["max_abs_delta_total"] > 0


def test_series_dedupe_differences_are_non_negative(report):
    section = report["series_dedupe"]
    assert section["unit_filter"] == "count"
    for metric in ("labour_approval", "deaths"):
        block = section[metric]
        assert block["duplicate_entity_years"] >= 0
        assert block["caption_agnostic_diagnostic"]["duplicate_entity_years"] >= 0
        for group in block["groups"]:
            assert group["naive_sum"] >= group["deduplicated_sum"]
            assert group["difference_naive_minus_deduped"] >= 0
            assert group["duplicate_entity_years"] >= 0
            assert group["duplicate_rows_dropped"] >= 0
    assert section["deaths"]["chosen_rule"]


def test_series_dedupe_partitions_incompatible_keys():
    frame = pd.DataFrame([
        {"metric": "deaths", "unit": "count", "dimension": "country",
         "year_basis": "fiscal", "gender": None, "caption": "Table A",
         "name": "Malaysia", "fiscal_year": "2010/11", "report": "r2015",
         "count": 100},
        {"metric": "deaths", "unit": "count", "dimension": "country",
         "year_basis": "fiscal", "gender": None, "caption": "Table A",
         "name": "Malaysia", "fiscal_year": "2010/11", "report": "r2020",
         "count": 80},
        {"metric": "deaths", "unit": "count", "dimension": "country",
         "year_basis": "fiscal", "gender": None, "caption": "Table A",
         "name": "Malaysia", "fiscal_year": "2011/12", "report": "r2015",
         "count": 20},
        {"metric": "deaths", "unit": "percent", "dimension": "country",
         "year_basis": "fiscal", "gender": None, "caption": "Table A",
         "name": "Malaysia", "fiscal_year": "2010/11", "report": "r2020",
         "count": 5},
    ])
    result = rob._dedupe_metric(frame, "deaths")
    count_groups = [g for g in result["groups"] if g["unit"] == "count"]
    assert len(count_groups) == 1
    group = count_groups[0]
    assert group["naive_sum"] == 200
    assert group["deduplicated_sum"] == 100
    assert group["difference_naive_minus_deduped"] == 100
    assert group["duplicate_entity_years"] == 1
    assert result["duplicate_entity_years"] == 1
