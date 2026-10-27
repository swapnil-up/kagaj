"""Tests for the Phase 0 migration research data layer."""

import json

import pytest

pytest.importorskip("pandas")

from migration_parser.research import audit, datasets


def test_load_panel_filters_to_safe_rows():
    df = datasets.load_panel()
    assert len(df) == 50052
    assert df["analysis_safe"].all()
    assert set(df["row_type"]) == {"detail"}
    assert set(df["granularity"]) <= {"month", "year"}


def test_country_year_keeps_one_basis_per_fiscal_year():
    panel = datasets.load_panel()
    cy = datasets.country_year(panel)
    assert not cy.duplicated(["fiscal_year", "country"]).any()
    assert (cy["count"] >= 0).all()
    annual = panel[(panel["section"] == "country")
                   & (panel["row_type"] == "detail")
                   & (panel["gender"] == "total")
                   & (panel["entity_resolved"])
                   & (panel["reconciled_fiscal_year"] == "2082/83")
                   & (panel["granularity"] == "year")]
    got = float(cy.loc[cy["fiscal_year"] == "2082/83", "count"].sum())
    assert got == float(annual["count"].sum())


def test_district_year_has_no_duplicate_entities():
    dist = datasets.district_year()
    assert not dist.duplicated(["fiscal_year", "district"]).any()
    assert (dist["count"] >= 0).all()


def test_audit_core_checks_are_clean():
    report = audit.build_audit()
    checks = report["checks"]
    assert checks["duplicate_dedup_keys"] == 0
    assert checks["negative_counts"] == 0
    assert checks["arithmetic"]["male_female_total_mismatches"] == 0
    assert checks["verified_false_rows"] > 0
    assert report["panel"]["rows_safe"] < report["panel"]["rows_all"]
    assert report["archive"]["male_female_total_mismatches"] == 0


def test_audit_outputs_are_written(tmp_path):
    report = audit.build_audit()
    paths = audit.write_outputs(report, tmp_path)
    assert paths["html"].exists()
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    payload = json.loads(paths["json"].read_text())
    assert payload["panel"]["rows_safe"] == report["panel"]["rows_safe"]
    assert "Phase 0 data audit" in paths["html"].read_text()


def test_report_loader_uses_safe_tracked_panel():
    pytest.importorskip("matplotlib")
    from migration_parser import report

    panel, series = report.load()
    assert panel["analysis_safe"].all()
    assert panel["count"].dtype.kind in {"i", "u"}
    assert len(series) > 0


@pytest.fixture(scope="module")
def pattern_report():
    from migration_parser.research.patterns import build_patterns

    return build_patterns()


def test_pattern_metrics_use_safe_panel(pattern_report):
    annual = pattern_report["annual"]
    assert [r["fiscal_year"] for r in annual][-1] == "2083/84"
    assert all(r["count"] > 0 for r in annual)
    assert any(r["country"] == "Malaysia" and r["growth_pct"] < 0
               for r in pattern_report["destinations"]["recovery"])
    assert pattern_report["districts"]["convergence"]["spearman"] is not None
    assert pattern_report["monthly"]["modern"]
    assert pattern_report["monthly"]["archive"]
    assert pattern_report["channels"]["reentry"]
    assert all(0 <= r["reentry_share_pct"] <= 100
               for r in pattern_report["channels"]["reentry"])


def test_pattern_outputs_are_written(pattern_report, tmp_path):
    from migration_parser.research.pattern_book import write_outputs

    paths = write_outputs(pattern_report, tmp_path)
    assert paths["html"].exists()
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    html_text = paths["html"].read_text()
    assert "Phase 1" in html_text
    assert "data:image/png;base64," in html_text
    payload = json.loads(paths["json"].read_text())
    assert payload["basis"]["rows"] == pattern_report["basis"]["rows"]
    assert payload["hypotheses"]


def test_district_gender_swaps_are_repaired():
    from migration_parser.research.datasets import country_gender_year

    district = datasets.district_gender_year().groupby(
        ["fiscal_year", "gender"])["count"].sum().unstack(fill_value=0)
    country = datasets.country_gender_year().groupby(
        ["fiscal_year", "gender"])["count"].sum().unstack(fill_value=0)
    for gender in ("male", "female"):
        assert abs(district.loc["2078/79", gender]
                   - country.loc["2078/79", gender]) <= 2
    assert district.loc["2075/76", "female"] < district.loc["2075/76", "male"]
