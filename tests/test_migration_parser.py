"""Tests for migration_parser — model templates, verification, periods."""

import csv
import json
from pathlib import Path

import pytest

from migration_parser import normalize
from migration_parser.annex import (
    ANNEX_COUNTRY,
    ANNEX_DISTRICT,
    extract_country_table,
    extract_district_table,
)
from migration_parser.agencies import _find_summary, _page_lines, parse_window
from migration_parser.model import DocMeta, ExtractResult, WideRow, channels_for
from migration_parser.parser import melt
from migration_parser.periods import (
    classify_doc_type,
    parse_ad_window,
    parse_bs_period,
)
from migration_parser.series import (
    _clean_name,
    _scalar,
    classify_metric,
    extract_calendar_year_matrix,
    extract_cause_country,
    extract_cause_country_year,
    extract_cause_of_death_year,
    extract_country_snapshot,
    extract_cross_tab,
    extract_destination_gender_crosstab,
    extract_measure_crosstab,
    extract_migration_cost,
    extract_mrrc_cases,
    extract_occupation_profile,
    extract_remittance_cost,
    extract_remittance_households,
    extract_remittance_use,
    extract_year_gender_blocks,
    extract_year_matrix,
    norm_cal_year,
    norm_year,
)
from migration_parser.verify import verify

# (male, female) per channel group; totals derived in _nums().
_MODERN = {
    "recruiting_agency": (10, 5),
    "individual_new": (20, 10),
    "g2g": (1, 2),
    "individual_reentry": (4, 6),
    "legalization": (3, 1),
}
_OLD = {
    "recruiting_agency": (10, 5),
    "new_entry": (20, 10),
    "legalized_entry": (3, 1),
    "re_entry": (4, 6),
}


def _nums(chans, groups):
    out = []
    for c in chans[:-2]:
        m, f = groups[c]
        out += [m, f, m + f]
    comp_m = sum(groups[c][0] for c in chans[:-2])
    comp_f = sum(groups[c][1] for c in chans[:-2])
    out += [comp_m, comp_f, comp_m + comp_f]
    re_c = next(c for c in chans if c in ("individual_reentry", "re_entry"))
    rr_m, rr_f = groups[re_c]
    out += [comp_m - rr_m, comp_f - rr_f, (comp_m - rr_m) + (comp_f - rr_f)]
    return out


def _row(section, name, nums, is_total=False):
    return WideRow(section=section, name=name, sn="1", nums=nums,
                   is_total=is_total, page=1)


def _result(rows):
    return ExtractResult(meta=DocMeta(), wide_rows=rows)


def test_modern_template_verifies():
    chans = channels_for(21)
    nums = _nums(chans, _MODERN)
    assert len(nums) == 21
    res = _result([_row("country", "Qatar", nums),
                   _row("country", "Total", nums, is_total=True)])
    report = verify(res)
    assert report.ok, report.failures


def test_old_template_verifies():
    chans = channels_for(18)
    nums = _nums(chans, _OLD)
    assert len(nums) == 18
    res = _result([_row("district", "Achham", nums),
                   _row("district", "Total", nums, is_total=True)])
    report = verify(res)
    assert report.ok, report.failures


def test_male_female_mismatch_fails():
    chans = channels_for(21)
    nums = _nums(chans, _MODERN)
    nums[2] += 1  # break recruiting_agency total
    res = _result([_row("country", "Qatar", nums),
                   _row("country", "Total", nums, is_total=True)])
    report = verify(res)
    assert not report.ok
    assert any(c.kind == "male_female_total" for c in report.failures)


def test_missing_total_fails():
    chans = channels_for(21)
    nums = _nums(chans, _MODERN)
    res = _result([_row("country", "Qatar", nums)])
    report = verify(res)
    assert not report.ok
    assert any(c.kind == "missing_total" for c in report.failures)


def test_melt_expands_channels_and_genders():
    chans = channels_for(21)
    res = _result([_row("country", "Qatar", _nums(chans, _MODERN))])
    rows = melt(res)
    assert len(rows) == 21
    assert {r["channel"] for r in rows} == set(chans)
    assert {r["gender"] for r in rows} == {"male", "female", "total"}
    # Old template melts to 18 rows with its own channel names.
    old = _result([_row("district", "Achham", _nums(channels_for(18), _OLD))])
    assert len(melt(old)) == 18


def test_parse_ad_window():
    txt = "Report on Final Approved List from 2025-10-18 to 2025-11-16"
    assert parse_ad_window(txt) == ("2025-10-18", "2025-11-16")
    assert parse_ad_window("no window here") == ("", "")


def test_parse_bs_period_and_type():
    assert parse_bs_period("२०८३ श्रावण महिनाको श्रम स्वीकृति विवरण") == "2083 श्रावण"
    assert classify_doc_type("वार्षिक श्रम स्वीकृति विवरण") == "annual"
    assert classify_doc_type("२०८२ जेष्ठ महिनाको श्रम स्वीकृति विवरण") == "single_month"


def test_norm_year():
    assert norm_year("2008/09") == "2008/09"
    assert norm_year("2008-2009") == "2008/09"
    assert norm_year("2074.75") == ""
    assert norm_year("Malaysia") == ""


def test_classify_metric():
    assert classify_metric("Table 8. Incident of death, by country") == "deaths"
    assert classify_metric("Table 10. Suicide in destination countries") == "deaths"
    assert classify_metric("Reported cases of disability") == "disability_compensation"
    assert classify_metric("Status of migrant workers' complaints") == "complaints"
    assert classify_metric("Number of male workers issued a labour permit") == "labour_approval"


def test_extract_year_matrix():
    rows = [
        ["Country/Year", "2008/09", "2009/10", "Total"],
        ["Malaysia", "15", "1 363", "1,378"],
        ["Qatar", "2", "3", "5"],
        ["Total", "17", "1,366", "1,383"],
    ]
    got = extract_year_matrix(rows, "Table 8. Incident of death, by country", 1, "r")
    assert len(got) == 4
    assert all(r["metric"] == "deaths" for r in got)
    assert all(r["unit"] == "count" for r in got)
    mal = {r["fiscal_year"]: r["count"] for r in got if r["name"] == "Malaysia"}
    assert mal == {"2008/09": 15, "2009/10": 1363}  # space separator handled


def test_extract_year_matrix_row_label_period_does_not_flip_unit():
    # A period in a *row label* (e.g. "Rep. of Korea") must not mark the whole
    # count table as `percent` (regression for the flawed any-cell heuristic).
    rows = [
        ["Country/Year", "2008/09", "2009/10", "Total"],
        ["Rep. of Korea", "1", "6", "7"],
        ["U.A.E.", "13", "53", "66"],
    ]
    got = extract_year_matrix(rows, "Table 8. Incident of death, by country", 1, "r")
    assert got and all(r["unit"] == "count" for r in got)


def test_extract_year_matrix_share_header_is_percent():
    rows = [
        ["District/Year", "2008/09", "2009/10", "Total share in six years"],
        ["Jhapa", "18", "20", "6.1"],
    ]
    got = extract_year_matrix(rows, "Table 3. Yearly pattern of labour migrants", 1, "r")
    assert got and all(r["unit"] == "percent" for r in got)


def test_extract_year_matrix_decimal_majority_is_percent():
    rows = [
        ["Province", "2008/09", "2009/10"],
        ["Bagmati", "33.1", "13.6"],
        ["Koshi", "30.6", "15.1"],
    ]
    got = extract_year_matrix(rows, "Table 18. Labour migration and caste", 1, "r")
    assert got and all(r["unit"] == "percent" for r in got)


def test_extract_year_matrix_rejects_crosstab():
    rows = [
        ["Country", "2008/09", "2009/10"],
        ["Malaysia", "1", "2"],
        ["Malaysia", "3", "4"],  # duplicate name×year → cross-tab, not a series
        ["Qatar", "5", "6"],
    ]
    assert extract_year_matrix(rows, "Table", 1, "r") == []


def test_extract_cause_of_death_year_reads_printed_totals():
    # migration_2020 "TABLE 16: Cause of Death by Year": years run down col 0,
    # causes across, ending in a printed Total M/F pair per row.
    rows = [
        ["FISCAL YEAR", "CAUSE OF DEATH", "", "", "Total", ""],
        ["", "CARDIAC ARREST", "SUICIDE", "OTHER CAUSES", "", ""],
        ["", "", "", "", "M", "F"],
        ["2008/09", "26", "9", "15", "87", "3"],
        ["2014/15", "268", "113", "54", "1000", "6"],
        ["Total", "294", "122", "69", "1087", "9"],
    ]
    got = extract_cause_of_death_year(rows, "TABLE 16: Cause of Death by Year", 103, "migration_2020")
    assert got
    assert all(r["metric"] == "deaths" and r["gender"] in {"male", "female", "total"} for r in got)
    tot = {r["fiscal_year"]: r["count"] for r in got if r["gender"] == "total"}
    assert tot == {"2008/09": 90, "2014/15": 1006}  # M + F
    mal = {r["fiscal_year"]: r["count"] for r in got if r["gender"] == "male"}
    assert mal == {"2008/09": 87, "2014/15": 1000}


def test_extract_cause_of_death_year_sums_cause_cells():
    # migration_2024 "Table 4.1: Cause of Death, 2008/09–2023/24": years down
    # col 0, causes across, no sex columns — all-cause = row sum of causes.
    rows = [
        ["Fiscal Year", "Cardiac Arrest", "Natural Causes", "Other Causes"],
        ["2008/09", "26", "24", "40"],
        ["2009/10", "106", "118", "194"],
        ["Total", "132", "142", "234"],
    ]
    got = extract_cause_of_death_year(
        rows, "Table 4.1: Cause of Death, 2008/09–2023/24", 81, "migration_2024")
    assert {r["fiscal_year"]: r["count"] for r in got} == {"2008/09": 90, "2009/10": 418}
    assert all(r["gender"] == "total" and r["metric"] == "deaths" for r in got)


def test_extract_cause_of_death_year_requires_caption():
    rows = [["", "", "M", "F"], ["2008/09", "x", "87", "3"], ["2009/10", "y", "400", "18"]]
    assert extract_cause_of_death_year(rows, "TABLE 17: Cause of Death by Country", 1, "r") == []
    # status-report "by sex" cause tables must not be summed as all-cause
    assert extract_cause_of_death_year(
        rows, "Table 13. Reported cause of death among labour migrants, by sex, 2008/09–2014/15",
        1, "r") == []


def test_extract_cause_country_year_captures_cause_and_sex():
    # status_2014_15 DATASET 7: one table per cause, fiscal years across the top
    # with M/F beneath (year only on the M column), country down col 0.
    rows = [
        ["Country", "Natural cause", None, None, None, None],
        [None, "2008/09", None, "2009/10", None, "Total"],
        [None, "M", "F", "M", "F", "M+F"],
        ["Saudi Arabia", "16", "", "51", "1", "68"],
        ["Malaysia", "1", "2", "31", "3", "37"],
        ["total ", "17", "2", "82", "4", "105"],
    ]
    cap = ("DATASET 7. Number of deaths among Nepali migrant workers while "
           "working abroad, by cause of death, destination country and sex, "
           "2008/9–2014/15")
    got = extract_cause_country_year(rows, cap, 100, "status_2014_15")
    assert got and all(r["metric"] == "deaths_by_cause" for r in got)
    assert all(r["note"] == "natural cause" and r["dimension"] == "country" for r in got)
    # both sexes captured, with the year forward-filled onto the F column
    assert {(r["name"], r["fiscal_year"], r["gender"]): r["count"] for r in got} == {
        ("Saudi Arabia", "2008/09", "female"): 0,  # blank cell → 0
        ("Saudi Arabia", "2008/09", "male"): 16,
        ("Saudi Arabia", "2009/10", "male"): 51,
        ("Saudi Arabia", "2009/10", "female"): 1,
        ("Malaysia", "2008/09", "male"): 1,
        ("Malaysia", "2008/09", "female"): 2,
        ("Malaysia", "2009/10", "male"): 31,
        ("Malaysia", "2009/10", "female"): 3,
    }
    # grand-total row and the (genderless) Total column are dropped
    assert not any(r["name"].lower().startswith("total") for r in got)


def test_extract_cause_country_year_requires_caption():
    rows = [["Country", "Natural cause", None], [None, "2008/09", None],
            [None, "M", "F"], ["Malaysia", "1", "2"]]
    assert extract_cause_country_year(rows, "Table 8. Deaths by country", 1, "r") == []


def test_series_key_includes_note():
    from migration_parser.series import SERIES_KEY_FIELDS, series_key
    assert "note" in SERIES_KEY_FIELDS
    a = {"report": "r", "source_page": 1, "caption": "c", "metric": "deaths_by_cause",
         "dimension": "country", "unit": "count", "year_basis": "fiscal",
         "gender": "male", "note": "natural cause"}
    b = {**a, "note": "workplace accident"}
    assert series_key(a) != series_key(b)


def test_extract_year_gender_blocks_skips_grand_total():
    # Annex 13 shape: District | 2022/23 M/F/T | 2023/24 M/F/T | Total M/F/T.
    rows = [
        ["Province", "District", "2022/23", None, None, "2023/24", None, None, "Total", None, None],
        ["", "", "Male", "Female", "Total", "Male", "Women", "Total", "Male", "Women", "Total"],
        ["Koshi", "Taplejung", "3,161", "257", "3,418", "2,588", "152", "2,740", "5,749", "409", "6,158"],
        ["", "Total", "3,161", "257", "3,418", "2,588", "152", "2,740", "5,749", "409", "6,158"],
        ["", "Grand Total", "503,037", "42,986", "546,023", "486,475", "50,771", "537,246",
         "989,512", "93,757", "1,083,269"],
    ]
    got = extract_year_gender_blocks(rows, "Annex 13: Number of returnee migrants", 147,
                                     "migration_2024", "return_migration", "district")
    assert {r["name"] for r in got} == {"Taplejung"}
    assert all(r["metric"] == "return_migration" for r in got)
    t = {(r["fiscal_year"], r["gender"]): r["count"] for r in got}
    assert t[("2022/23", "male")] == 3161
    assert t[("2022/23", "female")] == 257
    assert t[("2022/23", "total")] == 3418
    assert t[("2023/24", "female")] == 152  # "Women" maps to female


def test_extract_cross_tab_needs_year_tokens():
    assert extract_cross_tab(
        [["", "Male", "Female"], ["x", "1", "2"]], "Table 4.4", 1, "r") == []


def test_extract_occupation_profile_counts_not_percentages():
    # status-report T25: Occupation | Male Female Total | Percentage M F T.
    rows = [
        ["Occupation", "Male", "Female", "Total", "Percentage", "", ""],
        ["", "", "", "", "M", "F", "T"],
        ["Factory worker", "54 512", "1 697", "56 209", "56.81", "84.55", "59.52"],
        ["Security guard", "10 984", "0", "10 984", "11.8", "0", "11.63"],
        ["Total", "65 496", "1 697", "67 193", "100", "100", "100"],
    ]
    got = extract_occupation_profile(
        rows, "Table 25: Occupation profile: Malaysia, 2016/17, via recruitment agency only", 67,
        "status_2015_17")
    assert {r["name"] for r in got} == {"Factory worker", "Security guard"}
    assert all(r["dimension"] == "occupation" and r["note"] == "Malaysia"
               and r["fiscal_year"] == "2016/17" and r["unit"] == "count" for r in got)
    mal = {(r["name"], r["gender"]): r["count"] for r in got}
    assert mal[("Factory worker", "male")] == 54512   # space thousands parsed
    assert mal[("Factory worker", "total")] == 56209
    assert mal[("Security guard", "female")] == 0
    # percentage block (cols 4-6) must not be emitted
    assert not any(r["count"] in {5681, 8455, 5952} for r in got)


def test_extract_occupation_profile_requires_destination_caption():
    rows = [["Occupation", "Male", "Female", "Total"],
            ["x", "1", "2", "3"], ["y", "4", "5", "6"]]
    assert extract_occupation_profile(rows, "Table 21: Skills categorization", 1, "r") == []


def test_extract_calendar_year_matrix():
    rows = [
        ["Status of Residence", "2013", "2014"],
        ["Engineer/Specialist in humanities/\nInternational services", "1,251", "1,484"],
        ["Skilled labour", "6775", "7412"],
        ["Total", "8026", "8896"],
    ]
    got = extract_calendar_year_matrix(
        rows, "Table 3.19: Number of Mid- to Long-Term Nepali Residents in Japan, 2013–2023",
        75, "migration_2024")
    assert len(got) == 4
    assert all(r["year_basis"] == "calendar" and r["dimension"] == "residence_status"
               and r["metric"] == "migration_stock" for r in got)
    assert {(r["name"], r["fiscal_year"]): r["count"] for r in got}[
        ("Skilled labour", "2013")] == 6775
    assert norm_cal_year("2013") == "2013" and norm_cal_year("2008/09") == ""


def test_clean_name_collapses_whitespace():
    assert _clean_name("Nawalparasi\nEast") == "Nawalparasi East"
    assert _clean_name("  Grand Total  ") == "Grand"


def test_scalar_keeps_percent_decimals():
    assert _scalar("25.6", "percent") == 25.6
    assert _scalar("1.08 %", "percent") == 1.08
    assert _scalar("1,234", "percent") == 1234.0
    assert _scalar("547", "count") == 547
    assert _scalar("", "percent") == 0


def test_extract_measure_crosstab_skill_by_mode():
    rows = [
        ["Fiscal Year", "Skill", "Modes of Labour Approval", "", ""],
        ["", "", "G2G", "Individual", "Recruitment Agencies"],
        ["2022/23", "Professional", "0.1", "41.0", "58.8"],
        ["", "Skilled", "5.7", "16.8", "77.6"],
        ["", "Total", "4.3", "14.0", "81.7"],
        ["2023/24", "Professional", "0.1", "36.3", "63.7"],
        ["", "Skilled", "3.1", "22.9", "74.0"],
    ]
    got = extract_measure_crosstab(
        rows, "Table 3.7: New Labour Approvals, 2022/23–2023/24", 56, "migration_2024")
    key = {(r["name"], r["fiscal_year"], r["note"]): r["count"] for r in got}
    assert key[("Skilled", "2022/23", "G2G")] == 5.7
    assert key[("Skilled", "2022/23", "Recruitment Agencies")] == 77.6
    assert key[("Skilled", "2023/24", "G2G")] == 3.1
    assert all(r["dimension"] == "skill" and r["unit"] == "percent" for r in got)


def test_extract_measure_crosstab_occupation_by_mode_sex():
    rows = [
        ["", "Occupational Category", "G2G", "", "", "Individual", "", ""],
        ["", "", "Female", "Male", "Total", "Female", "Male", "Total"],
        ["2022/23", "Elementary Occupations", "94.5", "97.4", "97.2", "39.1", "36.5", "37.1"],
        ["", "Service & Sales", "0.0", "0.0", "0.0", "37.6", "28.1", "30.2"],
    ]
    got = extract_measure_crosstab(
        rows, "Table 3.13: New Labour Approvals, 2022/23–2023/24", 61, "migration_2024")
    key = {(r["name"], r["note"], r["gender"]): r["count"] for r in got}
    assert key[("Elementary Occupations", "G2G", "female")] == 94.5
    assert key[("Elementary Occupations", "G2G", "male")] == 97.4
    assert key[("Elementary Occupations", "Individual", "female")] == 39.1
    assert all(r["dimension"] == "occupation" for r in got)


def test_extract_measure_crosstab_total_n_is_count():
    rows = [
        ["", "Destination Country", "Skilled", "Total %", "Total N"],
        ["2022/23", "Malaysia", "64.8", "100", "259,591"],
        ["", "Cyprus", "18.8", "100", "5,317"],
    ]
    got = extract_measure_crosstab(
        rows, "Table 3.10: New Labour Approvals, 2022/23–2023/24", 59, "migration_2024")
    by = {(r["name"], r["note"]): (r["unit"], r["count"]) for r in got}
    assert by[("Malaysia", "Skilled")] == ("percent", 64.8)
    assert by[("Malaysia", "Total N")] == ("count", 259591)
    assert all(r["dimension"] == "country" for r in got)


def test_extract_country_snapshot_paired_and_sectioned():
    paired = [
        ["Country", "Number", "Country", "Number"],
        ["Saudi Arabia", "547", "Cyprus", "4"],
        ["UAE", "242", "Hong Kong", "3"],
    ]
    got = extract_country_snapshot(
        paired, "Table 4.5: Number of Nepali Migrants in Jail and Detention Centres Abroad",
        83, "migration_2024")
    assert {(r["name"], r["count"]) for r in got} == {
        ("Saudi Arabia", 547), ("Cyprus", 4), ("UAE", 242), ("Hong Kong", 3)}
    assert all(r["metric"] == "detention" and r["year_basis"] == "snapshot" for r in got)

    sectioned = [
        ["Country", "Number"],
        ["Hospitalised Nepali Migrants", None],
        ["Qatar", "11"],
        ["South Korea", "4"],
        ["Nepali Migrants in Shelters", None],
        ["South Korea", "400"],
    ]
    got = extract_country_snapshot(
        sectioned, "Table 4.6: Number of Nepali Migrants Hospitalised or in Shelters Abroad",
        84, "migration_2024")
    assert {(r["name"], r["note"]) for r in got} == {
        ("Qatar", "Hospitalised Nepali Migrants"),
        ("South Korea", "Hospitalised Nepali Migrants"),
        ("South Korea", "Nepali Migrants in Shelters")}
    assert all(r["metric"] == "hospitalisation" for r in got)


def test_extract_mrrc_cases_percent_and_total_n():
    rows = [
        ["Type of Case", "Total (2022/23 and 2023/24)", "", ""],
        ["", "Female", "Male", "Total"],
        ["Cheating", "25.6", "47.1", "45.5"],
        ["Other", "4.3", "1.4", "1.6"],
        ["Total %", "100", "100", "100"],
        ["Total N", "1,069", "13,281", "14,350"],
    ]
    got = extract_mrrc_cases(
        rows, "Table 4.7: Cases Registered at Migrant Resource Centres, 2022/23–2023/24",
        86, "migration_2024")
    pct = {(r["name"], r["gender"]): r["count"] for r in got if r["unit"] == "percent"}
    assert pct[("Cheating", "female")] == 25.6
    assert ("Total", "female") not in pct  # Total % skipped
    cnt = {r["gender"]: r["count"] for r in got if r["unit"] == "count"}
    assert cnt == {"female": 1069, "male": 13281, "total": 14350}
    assert all(r["name"] == "all cases" for r in got if r["unit"] == "count")


def test_extract_remittance_households_units():
    rows = [
        ["Province", "Per cent of HHs Receiving Remittance (%)", "Amount per remitter (NPR)"],
        ["Koshi", "31.0", "281,973"],
        ["Madhesh", "37.9", "134,568"],
    ]
    got = extract_remittance_households(
        rows, "Table 4.8: Remittance Receiving Households by Provinces", 87, "migration_2024")
    pct = {(r["name"], r["unit"]): r["count"] for r in got}
    assert pct[("Koshi", "percent")] == 31.0
    assert pct[("Koshi", "npr")] == 281973
    assert all(r["dimension"] == "province" for r in got)


def test_extract_remittance_use_priority_and_year():
    rows = [
        ["Use", "First Priority", "", "Second Priority", ""],
        ["", "2011", "2023", "2011", "2023"],
        ["Daily consumption", "69.3", "72.3", "24.3", "18.2"],
        ["Repay loan", "15.9", "13.5", "17.4", "19.4"],
    ]
    got = extract_remittance_use(rows, "Table 4.9: Use of Remittances (%)", 89, "migration_2024")
    key = {(r["name"], r["fiscal_year"], r["note"]): r["count"] for r in got}
    assert key[("Daily consumption", "2023", "first priority")] == 72.3
    assert key[("Daily consumption", "2011", "second priority")] == 24.3
    assert all(r["year_basis"] == "calendar" and r["unit"] == "percent" for r in got)


def test_extract_destination_gender_crosstab_counts_and_percent():
    rows = [
        ["Place of destination", "Male", "", "Female", "", "Total", ""],
        ["", "No.", "%", "No.", "%", "No.", "%"],
        ["Qatar", "71,322", "30.2", "3,702", "1.6", "75,024", "31.76"],
        ["Saudi Arabia", "44,493", "18.8", "1,587", "0.7", "46,080", "19.51"],
    ]
    got = extract_destination_gender_crosstab(
        rows, "Table 8: Labour permits issued by place of destination and sex, 2018/2019",
        77, "country_intro_2019")
    key = {(r["name"], r["gender"], r["unit"]): r["count"] for r in got}
    assert key[("Qatar", "male", "count")] == 71322
    assert key[("Qatar", "female", "count")] == 3702
    assert key[("Qatar", "total", "count")] == 75024
    assert key[("Qatar", "male", "percent")] == 30.2
    assert all(r["fiscal_year"] == "2018/19" and r["dimension"] == "country" for r in got)


def test_extract_cause_country():
    rows = [
        ["COUNTRY", "CAUSE OF DEATH", "", ""],
        ["", "CARDIAC ARREST", "SUICIDE", "OTHER CAUSES"],
        ["MALAYSIA", "330", "240", "184"],
        ["QATAR", "489", "87", "119"],
    ]
    got = extract_cause_country(rows, "TABLE 17: CAUSE OF DEATH BY COUNTRY", 103, "migration_2020")
    key = {(r["name"], r["note"]): r["count"] for r in got}
    assert key[("MALAYSIA", "suicide")] == 240
    assert all(r["metric"] == "deaths_by_cause" and r["year_basis"] == "snapshot" for r in got)


def test_extract_remittance_cost():
    rows = [
        ["2019 Q3 (Total Cost %)", "500 USD", "200 USD"],
        ["Malaysia", "2.5", "3.36"],
        ["Oman", "3.8", "5.69"],
    ]
    got = extract_remittance_cost(rows, "TABLE 19: REMITTANCE TRANSFER COSTS", 115, "migration_2020")
    key = {(r["name"], r["note"]): r["count"] for r in got}
    assert key[("Malaysia", "500 USD")] == 2.5
    assert all(r["metric"] == "remittance_cost" and r["unit"] == "percent" for r in got)


def test_extract_migration_cost():
    rows = [
        ["Country", "Average cost (USD)", "Average monthly earnings (USD)"],
        ["Australia", "10,849", "1,589"],
        ["Bahrain", "1,404", "418"],
    ]
    got = extract_migration_cost(
        rows, "Table 12: Cost of migration versus average earnings by destination country",
        89, "country_intro_2019")
    key = {(r["name"], r["note"]): r["count"] for r in got}
    assert key[("Australia", "Average cost (USD)")] == 10849
    assert all(r["metric"] == "migration_cost" and r["unit"] == "usd" for r in got)


def _cells(*groups):
    """[m, f, m+f] per group → flat list of ints."""
    out = []
    for m, f in groups:
        out += [str(m), str(f), str(m + f)]
    return out


def test_annex_country_ix_verifies():
    # components sum to Total With; With − Re-Entry == Total Without.
    ra, new, reg, re = (10, 5), (20, 10), (3, 1), (4, 6)
    with_ = tuple(sum(g[i] for g in (ra, new, reg, re)) for i in (0, 1))
    without = (with_[0] - re[0], with_[1] - re[1])
    rows = [
        ["Country", "Recruiting Agency", None, None, "New Entry", None, None,
         "Regularized Entry", None, None, "Re-Entry", None, None,
         "Total With Re-Entry", None, None, "Total Without Re-Entry", None, None],
        [None] * 19,
        ["Testland"] + _cells(ra, new, reg, re, with_, without),
    ]
    got, problems = extract_country_table(rows, ANNEX_COUNTRY["IX"], 144, "u", "d")
    assert problems == []
    assert len(got) == 6 * 3
    mal = {(r["channel"], r["gender"]): r["count"] for r in got}
    assert mal[("recruiting_agency", "total")] == 15
    assert mal[("total_with_reentry", "total")] == 59
    assert mal[("total_without_reentry", "total")] == 49


def test_annex_country_x_swapped_totals_verify():
    # Table X order: ... Total Without Renew, Total With Renew (swapped vs IX).
    ra, new, reg, renew = (10, 5), (20, 10), (3, 1), (4, 6)
    with_ = tuple(sum(g[i] for g in (ra, new, reg, renew)) for i in (0, 1))
    without = (with_[0] - renew[0], with_[1] - renew[1])
    rows = [
        ["Country", "Recruiting Agency", None, None, "Individual-New", None, None,
         "Individual-Regularization", None, None, "Individual-Renew", None, None,
         "Total Without Renew", None, None, "Total With Renew", None, None],
        [None] * 19,
        ["Testland"] + _cells(ra, new, reg, renew, without, with_),
    ]
    got, problems = extract_country_table(rows, ANNEX_COUNTRY["X"], 148, "u", "d")
    assert problems == []
    vals = {(r["channel"], r["gender"]): r["count"] for r in got}
    assert vals[("total_with_renew", "total")] == 59
    assert vals[("total_without_renew", "total")] == 49


def test_annex_country_flags_arithmetic_typo():
    ra, new, reg, re = (10, 5), (20, 10), (3, 1), (4, 6)
    with_ = tuple(sum(g[i] for g in (ra, new, reg, re)) for i in (0, 1))
    without = (with_[0] - re[0], with_[1] - re[1])
    cells = _cells(ra, new, reg, re, with_, without)
    cells[2] = "16"  # RA total printed 16 but M+F=15 (source typo)
    rows = [["Country"] + [None] * 18, [None] * 19, ["Testland"] + cells]
    _, problems = extract_country_table(rows, ANNEX_COUNTRY["IX"], 144, "u", "d")
    assert any("recruiting_agency" in p for p in problems)


def test_annex_district_verifies():
    rows = [
        ["District", "Men", "Women", "Total"],
        ["Kathmandu", "5", "3", "8"],
        ["Total", "5", "3", "8"],
    ]
    got, problems = extract_district_table(rows, ANNEX_DISTRICT["XI"], 152, "u", "d")
    assert problems == []
    assert [(r["gender"], r["count"]) for r in got] == [
        ("male", 5), ("female", 3), ("total", 8)]
    assert all(r["channel"] == "recruiting_agency" for r in got)


def test_annex_district_flags_mismatch():
    rows = [
        ["District", "Men", "Women", "Total"],
        ["Kathmandu", "5", "3", "9"],
    ]
    _, problems = extract_district_table(rows, ANNEX_DISTRICT["XI"], 152, "u", "d")
    assert len(problems) == 1


def test_agencies_parse_window():
    t = "Report on Prepermission List  from 2075 Ashad 2018-06-15 to 2018-07-16\n"
    assert parse_window(t) == ("2018-06-15", "2018-07-16")
    assert parse_window("no window here") == ("", "")


def test_agencies_find_summary():
    rows = [
        ["Government of Nepal", None, None, None, None],
        ["SN", "Country", "Male", "Female", "Total"],
        ["1", "Nepal", "5", "3", "8"],
        ["2", "Qatar", "10", "0", "10"],
        ["", "Total", "15", "3", "18"],
    ]
    detail, totals = _find_summary(rows)
    assert [d[1] for d in detail] == ["Nepal", "Qatar"]
    assert totals[0][1] == "Total"


def test_agencies_page_lines_rejoins_split_sn():
    lines = ["883", "86799 Malaysia", "A.N.S.ASSOCIATES PVT. LTD.",
             "100", "0", "100"]
    assert _page_lines("\n".join(lines)) == [
        "883 86799 Malaysia", "A.N.S.ASSOCIATES PVT. LTD.", "100", "0", "100"]
    # a lone number followed by a plain name is NOT joined
    line2 = ["0", "10", "NAME", "1", "0", "1"]
    assert _page_lines("\n".join(line2))[0] == "0"


# ---- entity + period normalisation ----------------------------------------

def test_normalize_country_variants():
    assert normalize.canonical_country("UAE")["name"] == "United Arab Emirates"
    assert normalize.canonical_country("uae")["iso3"] == "ARE"
    assert normalize.canonical_country("Saudi Arab")["name"] == "Saudi Arabia"
    assert normalize.canonical_country("Combodia")["name"] == "Cambodia"
    assert normalize.canonical_country("Myanmmar")["name"] == "Myanmar"
    assert normalize.canonical_country("Burma")["name"] == "Myanmar"
    assert normalize.canonical_country("Macau, SAR, China")["name"] == "Macau"
    assert normalize.canonical_country("Republic of Korea")["name"] == "South Korea"
    assert normalize.canonical_country("Ivory Coast")["name"] == "Cote d'Ivoire"
    assert normalize.canonical_country("AZERBAI")["name"] == "Azerbaijan"
    # Table-cell extraction can drop or split spaces.
    assert normalize.canonical_country("SaudiArabia")["name"] == "Saudi Arabia"
    assert normalize.canonical_country("BruneiDarussalam")["name"] == "Brunei Darussalam"
    assert normalize.canonical_country("UnitedStatesof America")["name"] == \
        "United States of America"
    assert normalize.canonical_country("Hongkong")["name"] == "Hong Kong"


def test_restore_country_spacing():
    assert normalize.restore_country_spacing("SaudiArabia") == "Saudi Arabia"
    assert normalize.restore_country_spacing("Republicof Korea") == "Republic of Korea"
    assert normalize.restore_country_spacing("FromEPS Angola") == "From EPS Angola"
    assert normalize.restore_country_spacing("BosniaHerzGovina") == "Bosnia Herz Govina"
    assert normalize.restore_country_spacing("Afghanistan") == "Afghanistan"


def test_normalize_country_flagged_and_unknown():
    # flagged entities resolve to a record but carry resolved=False
    assert normalize.canonical_country("Saipan")["resolved"] is False
    assert normalize.canonical_country("Republic o")["kind"] == "clipped"
    assert normalize.canonical_country("Narnia") is None


def test_normalize_district_variants_and_province():
    assert normalize.canonical_district("Acham")["name"] == "Achham"
    assert normalize.canonical_district("Acham")["province"] == "sudurpashchim"
    assert normalize.canonical_district("Mahotat ri")["name"] == "Mahottari"
    assert normalize.canonical_district("Kavrepalanchowk")["name"] == "Kavrepalanchok"
    assert normalize.canonical_district("Udaypur")["name"] == "Udayapur"
    assert normalize.canonical_district("Rukum East")["province"] == "lumbini"
    assert normalize.canonical_district("Rukum West")["province"] == "karnali"


def test_every_district_province_is_one_of_seven():
    # No compound "gandaki+lumbini" labels: every district maps to exactly one
    # modern province so a 7-province rollup is never polluted.
    provinces = {"koshi", "madhesh", "bagmati", "gandaki", "lumbini",
                 "karnali", "sudurpashchim"}
    for d in normalize._load_json("districts.json"):
        assert d.get("province") in provinces, d


def test_presplit_districts_use_hq_province_with_note():
    # Pre-2018 unified districts are assigned to their (historical) HQ province
    # and must carry an explanatory provenance note.
    nawal = normalize.canonical_district("Nawalparasi")
    assert nawal["province"] == "gandaki" and nawal["note"]
    rukum = normalize.canonical_district("Rukum")
    assert rukum["province"] == "karnali" and rukum["note"]
    # the note reaches the normalised output
    info = normalize.normalize_name("district", "Nawalparasi")
    assert info["note"] and info["province"] == "gandaki"


def test_parse_bs_month():
    year, month = normalize.parse_bs_month("2082 असोज")
    assert year == 2082 and month["name"] == "Ashwin" and month["index"] == 6
    year, month = normalize.parse_bs_month("2083 वैशाख")
    assert year == 2083 and month["index"] == 1
    assert normalize.parse_bs_month("2079/80") == (None, None)


def test_fiscal_year_of_month():
    assert normalize.fiscal_year_of_month(2082, 6) == "2082/83"   # Ashwin
    assert normalize.fiscal_year_of_month(2083, 1) == "2082/83"   # Baisakh 2083
    assert normalize.fiscal_year_of_month(2083, 5) == "2083/84"   # Bhadra
    assert normalize.fiscal_year_of_month(2084, 3) == "2083/84"   # Ashadh


def test_fiscal_year_for_row():
    # monthly periods
    assert normalize.fiscal_year_for_row("303", "2083 श्रावण") == "2083/84"
    assert normalize.fiscal_year_for_row("36", "2082 वैशाख") == "2081/82"
    assert normalize.fiscal_year_for_row("228", "2083 वैशाख") == "2082/83"
    # annual label
    assert normalize.fiscal_year_for_row("89", "2074/75") == "2074/75"
    # docs whose BS period the parser could not read -> doc-id map
    assert normalize.fiscal_year_for_row("33", "") == "2078/79"
    assert normalize.fiscal_year_for_row("89", "") == "2073/74"
    assert normalize.fiscal_year_for_row("332", "") == "2083/84"


def test_normalize_name_dispatch():
    assert normalize.normalize_name("country", "Qatar")["canonical"] == "Qatar"
    got = normalize.normalize_name("district", "TEHRATHUM")
    assert got["canonical"] == "Terhathum" and got["province"] == "koshi"


def test_every_panel_name_is_covered_by_reference_data():
    """Guard: any raw name in the shipped panel must resolve to an entity."""
    from migration_parser.paths import open_csv, panel_source
    missing = []
    with open_csv(panel_source(), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["row_type"] != "detail":
                continue
            if row["section"] == "country":
                ent = normalize.canonical_country(row["name"])
            elif row["section"] == "district":
                ent = normalize.canonical_district(row["name"])
            else:
                continue
            if ent is None:
                missing.append((row["section"], row["name"]))
    assert not missing, f"unmapped names: {sorted(set(missing))}"


# ---- channel reconciliation ------------------------------------------------

def test_canonical_channel_equivalences():
    assert normalize.canonical_channel("re_entry")["canonical"] == "individual_reentry"
    assert normalize.canonical_channel("individual_renew")["canonical"] == "individual_reentry"
    assert normalize.canonical_channel("legalized_entry")["canonical"] == "legalization"
    assert normalize.canonical_channel("regularized_entry")["canonical"] == "legalization"
    assert normalize.canonical_channel("individual_regularization")["canonical"] == "legalization"
    assert normalize.canonical_channel("total_with_renew")["canonical"] == "total_with_reentry"
    assert normalize.canonical_channel("total_without_renew")["canonical"] == "total_without_reentry"


def test_canonical_channel_classes():
    assert normalize.canonical_channel("recruiting_agency")["class"] == "component"
    assert normalize.canonical_channel("new_entry")["class"] == "component"
    assert normalize.canonical_channel("g2g")["class"] == "component"
    assert normalize.canonical_channel("total_with_reentry")["class"] == "aggregate"
    assert normalize.canonical_channel("individual")["class"] == "aggregate"
    assert normalize.canonical_channel("preapproval")["class"] == "measure"


def test_canonical_channel_new_entry_not_merged():
    # old-template new_entry must NOT be silently treated as individual_new
    got = normalize.canonical_channel("new_entry")
    assert got["canonical"] == "new_entry"


def test_canonical_channel_unknown_is_passthrough():
    got = normalize.canonical_channel("something_new")
    assert got == {"canonical": "something_new", "class": "unknown",
                   "label": "something_new", "reviewed": False}


def test_every_panel_channel_is_mapped():
    from migration_parser.paths import open_csv, panel_source
    unknown = set()
    with open_csv(panel_source(), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if normalize.canonical_channel(row["channel"])["class"] == "unknown":
                unknown.add(row["channel"])
    assert not unknown, f"unmapped channels: {sorted(unknown)}"


# ---- cross-document reconciliation -----------------------------------------

def test_classify_doc_type_month_beats_progress():
    assert classify_doc_type("भदौ महिनाको प्रगति विवरण") == "single_month"
    assert classify_doc_type("आ. ब. २०८२-८३ वार्षिक  प्रगति प्रतिवेदन") == "annual"
    assert classify_doc_type("२०८३ श्रावण महिनाको श्रम स्वीकृति विवरण") == "single_month"


def test_doc_granularity():
    assert normalize.doc_granularity("single_month") == "month"
    assert normalize.doc_granularity("annual") == "year"
    assert normalize.doc_granularity("annual", channel_class="measure") == "measure"
    assert normalize.doc_granularity("cumulative") == "month"


def test_annex_table_x_year_override():
    # Table X is printed FY2074/75 but its data is FY2018/19 -> overridden
    assert normalize.override_for("report2020_annex_X")["reconciled_fiscal_year"] == "2075/76"
    assert normalize.reconciled_fiscal_year("report2020_annex_X", "2074/75") == "2075/76"
    # unchanged docs / years pass through
    assert normalize.reconciled_fiscal_year("report2020_annex_IX", "2074/75") == "2074/75"
    assert normalize.reconciled_fiscal_year("278", "2082/83") == "2082/83"


def test_reconciliation_rule_and_key():
    rec = normalize.reconciliation()
    assert normalize.dedup_key_columns() == rec["dedup_key"]
    assert "granularity" in rec["dedup_key"] and "channel_canonical" in rec["dedup_key"]
    kinds = {g["kind"] for g in rec["overlap_groups"]}
    assert "annual_vs_months" in kinds and "dimension_pair" in kinds


# ---- panel-wide verification ----------------------------------------------

def test_channel_classes():
    cls = normalize.channel_classes()
    assert cls["recruiting_agency"] == "component"
    assert cls["total_with_reentry"] == "aggregate"
    assert cls["preapproval"] == "measure"


def _prow(doc, name, channel, gender, count, row_type="detail"):
    return {"doc_id": doc, "section": "country", "row_type": row_type,
            "name": name, "channel": channel, "gender": gender,
            "count": str(count), "verified": "True"}


def test_panel_verify_detects_component_mismatch():
    from migration_parser.panel_verify import verify_panel
    base = [
        _prow("d", "Nepal", "recruiting_agency", "total", 10),
        _prow("d", "Nepal", "individual_new", "total", 5),
        _prow("d", "Nepal", "g2g", "total", 3),
        _prow("d", "Nepal", "individual_reentry", "total", 2),
        _prow("d", "Nepal", "legalization", "total", 0),
        _prow("d", "Nepal", "total_with_reentry", "total", 20),
        _prow("d", "Nepal", "total_without_reentry", "total", 18),
        _prow("d", "Nepal", "recruiting_agency", "total", 10, "total"),
    ]
    assert verify_panel(base) == []
    bad = [dict(r) for r in base]
    bad[5]["count"] = "21"
    bad[6]["count"] = "19"
    fails = verify_panel(bad)
    assert [f.kind for f in fails] == ["components_with_reentry"]


def test_panel_verify_canonicalises_old_template_channels():
    from migration_parser.panel_verify import verify_panel
    # old template: new_entry/legalized_entry/re_entry are components
    rows = [
        _prow("d", "Nepal", "recruiting_agency", "total", 653),
        _prow("d", "Nepal", "new_entry", "total", 9),
        _prow("d", "Nepal", "legalized_entry", "total", 3),
        _prow("d", "Nepal", "re_entry", "total", 237),
        _prow("d", "Nepal", "total_with_reentry", "total", 902),
        _prow("d", "Nepal", "total_without_reentry", "total", 665),
    ]
    assert verify_panel(rows) == []


# ---- opendatanepal cross-check helpers -------------------------------------

def test_fiscal_year_for_ad():
    assert normalize.fiscal_year_for_ad("2019/20") == "2076/77"
    assert normalize.fiscal_year_for_ad("2021/22") == "2078/79"
    assert normalize.fiscal_year_for_ad("1900/01") is None
    assert normalize.fiscal_year_for_ad("") is None


def test_opendata_country_aliases():
    assert normalize.canonical_country("UK")["name"] == "United Kingdom"
    assert normalize.canonical_country("Macau SAR, China")["name"] == "Macau"
    assert normalize.canonical_country("UAE")["name"] == "United Arab Emirates"


def test_crosscheck_without_inputs_reports_download_hint(tmp_path, monkeypatch, capsys):
    from migration_parser.scripts import cmd_crosscheck as cc
    monkeypatch.setattr(cc, "OPENDATA", tmp_path / "opendatanepal")
    assert cc.main([]) == 2
    assert "--download" in capsys.readouterr().err


def test_crosscheck_download_fetches_all_resources(tmp_path, monkeypatch):
    from migration_parser.scripts import cmd_crosscheck as cc

    class Resp:
        content = b"a,b\n1,2\n"
        def raise_for_status(self):
            pass

    urls = []
    def fake_get(url, **kwargs):
        urls.append(url)
        assert kwargs["verify"] is True
        return Resp()

    monkeypatch.setattr(cc, "OPENDATA", tmp_path / "opendatanepal")
    monkeypatch.setattr(cc.requests, "get", fake_get)
    cc.download_opendata(log=lambda *_: None)
    assert set(urls) == set(cc.OPENDATA_RESOURCES.values())
    for name in cc.OPENDATA_RESOURCES:
        assert (tmp_path / "opendatanepal" / name).read_bytes() == Resp.content


def test_provenance_keeps_existing_attestation_without_cached_pdfs(tmp_path, monkeypatch):
    from migration_parser.scripts import cmd_provenance as prov
    att = tmp_path / "source_attestation.json"
    original = '{"docs": [{"serial": 1, "text_sha256": "x"}]}\n'
    att.write_text(original)
    monkeypatch.setattr(prov, "ATTESTATION", att)
    monkeypatch.setattr(prov, "MIGRATION_DIR", tmp_path)
    monkeypatch.setattr(prov.process, "load_manifest", lambda: [{"serial": 1, "doc_id": "1"}])
    monkeypatch.setattr(prov.process, "pdf_path", lambda e: tmp_path / "missing.pdf")
    assert prov.main([]) == 0
    assert att.read_text() == original


# ---- packaging / build -----------------------------------------------------

def test_codebook_columns_match_shipped_headers():
    from migration_parser.scripts import cmd_build
    cmd_build._verify_columns()  # raises SystemExit on drift


def test_cli_dispatch_covers_all_stages():
    from migration_parser import cli
    for stage in cli.STAGES:
        assert callable(cli._dispatch(stage))


def test_build_gunzip_is_deterministic(tmp_path, monkeypatch):
    import gzip
    from migration_parser.scripts import cmd_build
    monkeypatch.setattr(cmd_build, "MIGRATION_DIR", tmp_path)
    payload = b"a,b\n1,2\n3,4\n"
    (tmp_path / "panel_canonical.csv").write_bytes(payload)

    out = cmd_build.gunzip_panel()
    first = out.read_bytes()
    assert gzip.decompress(first) == payload
    assert cmd_build.gunzip_panel().read_bytes() == first  # mtime=0 -> stable


def test_build_keeps_existing_gzip_without_source(tmp_path, monkeypatch):
    import gzip
    from migration_parser.scripts import cmd_build
    monkeypatch.setattr(cmd_build, "MIGRATION_DIR", tmp_path)
    dst = tmp_path / "panel.csv.gz"
    with gzip.open(dst, "wb") as f:
        f.write(b"a,b\n1,2\n")

    assert cmd_build.gunzip_panel("panel.csv", "panel.csv.gz") == dst
    with gzip.open(dst, "rt", encoding="utf-8") as f:
        assert f.read() == "a,b\n1,2\n"


def test_panel_source_prefers_working_csv(tmp_path, monkeypatch):
    import gzip
    from migration_parser import paths
    monkeypatch.setattr(paths, "MIGRATION_DIR", tmp_path)
    gz = tmp_path / "panel.csv.gz"
    with gzip.open(gz, "wt", encoding="utf-8") as f:
        f.write("a\n1\n")
    assert paths.panel_source() == gz
    (tmp_path / "panel.csv").write_text("a\n2\n")
    assert paths.panel_source() == tmp_path / "panel.csv"


# ---- canonical safety / packaging invariants -------------------------------

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "datasets" / "labour-migration"
MIGRATION_MANIFEST = MIGRATION_DIR / "manifests" / "migration_manifest.json"


def _read_shipped(name: str) -> list[dict]:
    import gzip
    path = MIGRATION_DIR / name
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_canonical_is_additive_only():
    rows = _read_shipped("panel_canonical.csv.gz")
    assert rows
    assert {r["channel_class"] for r in rows} == {"component"}
    assert {r["row_type"] for r in rows} == {"detail"}


def test_rollup_holds_all_non_additive_rows():
    rollup = _read_shipped("panel_rollup.csv.gz")
    assert {r["channel_class"] for r in rollup} <= {"aggregate", "measure", "component"}
    assert any(r["channel_class"] == "aggregate" for r in rollup)
    # component-class rows in the rollup must be printed totals, never detail
    for r in rollup:
        if r["channel_class"] == "component":
            assert r["row_type"] in ("total", "grand_total")


def test_canonical_unique_on_dedup_key():
    rows = _read_shipped("panel_canonical.csv.gz")
    key_cols = normalize.dedup_key_columns()
    seen: dict[tuple, int] = {}
    for r in rows:
        k = tuple(r[c] for c in key_cols)
        seen[k] = seen.get(k, 0) + 1
    dups = [k for k, n in seen.items() if n > 1]
    assert not dups, f"{len(dups)} duplicate dedup-key groups, e.g. {dups[0]}"


def test_clipped_entities_are_resolved_from_pdf_text_trace():
    rows = _read_shipped("panel_canonical.csv.gz")
    doc332 = [r for r in rows if r["doc_id"] == "332"]
    assert not [r for r in doc332 if r["name_canonical"].startswith(
        ("Republic o (", "REPUBLI ("))]
    expected = {
        "South Korea": (9, 903),
        "Bulgaria": (14, 540),
        "North Macedonia": (30, 68),
        "Seychelles": (34, 64),
        "Republic of the Congo": (76, 2),
    }
    for name, (sn, total) in expected.items():
        block = [r for r in doc332
                 if r["name_canonical"] == name and r["gender"] == "total"]
        assert block, name
        assert {r["entity_resolved"] for r in block} == {"true"}
        if name == "Seychelles":
            assert block[0]["merged_rows"] == "2"
            assert block[0]["raw_names"] == "REPUBLI;Seychelles"
        else:
            assert {r["sn"] for r in block} == {str(sn)}
        assert sum(int(r["count"]) for r in block) == total


def test_normalize_name_resolves_doc332_serials():
    cases = {
        "9": ("South Korea", "KOR"),
        "14": ("Bulgaria", "BGR"),
        "30": ("North Macedonia", "MKD"),
        "55": ("Seychelles", "SYC"),
        "76": ("Republic of the Congo", "COG"),
    }
    for sn, (name, iso3) in cases.items():
        info = normalize.normalize_name("country", "Republic o", "332", sn)
        assert info["canonical"] == name
        assert info["resolved"] is True
        assert info["iso3"] == iso3


def test_analysis_safe_flag_definition():
    rows = _read_shipped("panel_canonical.csv.gz")
    for r in rows:
        resolved = r["entity_resolved"] == "true"
        verified = str(r["verified"]).strip().lower() == "true"
        reviewed = r["channel_reviewed"] == "true"
        # Safe default folds in channel_reviewed; the permissive flag does not.
        assert (r["analysis_safe"] == "true") == (resolved and verified and reviewed)
        assert (r["analysis_safe_permissive"] == "true") == (resolved and verified)
    assert any(r["channel_reviewed"] == "false" for r in rows)


def test_vocabularies_are_documented():
    from migration_parser.scripts import cmd_build
    cmd_build._check_vocabularies(cmd_build._vocabularies())


def test_build_fingerprint_is_verifiable():
    import hashlib
    import json
    import subprocess

    build = json.loads((MIGRATION_DIR / "build.json").read_text())
    commit = build["git"]["commit"]
    assert commit, "build.json has no recorded commit"
    assert build["git"]["dirty"] is False, "shipped build.json was made on a dirty tree"
    rc = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"],
                        cwd=MIGRATION_DIR.parent, capture_output=True)
    assert rc.returncode == 0, f"build commit {commit} is not an ancestor of HEAD"

    assert "panel_rollup.csv.gz" in build["files"]
    assert "period_windows.csv" in build["files"]
    for name, meta in build["files"].items():
        path = MIGRATION_DIR / name
        assert path.exists(), f"shipped artifact missing: {name}"
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        assert h == meta["sha256"], f"sha256 drift for {name}"


def test_period_merge_maps_dates_to_windows():
    pd = pytest.importorskip("pandas")
    from migration_parser import analysis
    df = pd.DataFrame({"d": ["1990-01-01", "2025-10-20"]})
    out = analysis.merge_periods(df, "d").set_index("d")
    assert not bool(out.loc["1990-01-01", "window_matched"])   # falls in no window
    assert bool(out.loc["2025-10-20", "window_matched"])
    assert out.loc["2025-10-20", "period_ad_start"]
    assert out.loc["2025-10-20", "period_ad_end"]


def test_fiscal_year_panel_avoids_month_year_double_count():
    pd = pytest.importorskip("pandas")
    from migration_parser import analysis
    df = pd.DataFrame({
        "reconciled_fiscal_year": ["2082/83", "2082/83", "2081/82"],
        "granularity": ["month", "year", "year"],
    })
    annual = analysis.fiscal_year_panel(df)
    assert list(annual["granularity"]) == ["year", "year"]
    monthly = analysis.fiscal_year_panel(df, prefer="month")
    assert list(monthly["granularity"]) == ["month", "year"]


def test_fiscal_year_calendar_anchors():
    # Shrawan 1 (fiscal-year start) dates from the authoritative BS calendar.
    fy = normalize.fiscal_years()
    anchors = {
        "2076/77": "2019-07-17",
        "2078/79": "2021-07-16",
        "2080/81": "2023-07-17",
        "2081/82": "2024-07-16",
        "2082/83": "2025-07-17",
    }
    for bs, ad_start in anchors.items():
        assert fy[bs]["ad_start"] == ad_start, bs


def test_preeti_decoder_known_tokens():
    from migration_parser.preeti import decode
    cases = {
        "g]kfn ;/sf/": "\u0928\u0947\u092a\u093e\u0932 \u0938\u0930\u0915\u093e\u0930",          # नेपाल सरकार
        "j}b]lzs /f]huf/ ljefu": "\u0935\u0948\u0926\u0947\u0936\u093f\u0915 \u0930\u094b\u091c\u0917\u093e\u0930 \u0935\u093f\u092d\u093e\u0917",  # वैदेशिक रोजगार विभाग
        "k'?if": "\u092a\u0941\u0930\u0941\u0937",   # पुरुष
        "dlxnf": "\u092e\u0939\u093f\u0932\u093e",   # महिला
        "hDdf": "\u091c\u092e\u094d\u092e\u093e",    # जम्मा
        "tLgs'g],": "\u0924\u0940\u0928\u0915\u0941\u0928\u0947,",
        "sf7df8f+}": "\u0915\u093e\u0920\u092e\u093e\u0921\u094c\u0902",  # काठमाडौं
        ";+=": "\u0938\u0902.",                       # सं.
    }
    for preeti, unicode_text in cases.items():
        assert decode(preeti) == unicode_text, preeti


def test_preeti_digits_and_empty():
    from migration_parser.preeti import ascii_digits, decode, has_devanagari
    assert decode("") == ""
    assert ascii_digits("\u0967\u0968\u0969") == "123"
    assert has_devanagari("नेपाल") and not has_devanagari("g]kfn")


def test_high_risk_channels_are_flagged_unreviewed():
    reviewed = normalize.channel_reviewed()
    assert reviewed["legalization"] is False
    assert reviewed["new_entry"] is False
    assert reviewed["individual_new"] is True


def test_channel_reviewed_lands_in_shipped_canonical():
    import gzip
    reviewed = normalize.channel_reviewed()
    with gzip.open(MIGRATION_DIR / "panel_canonical.csv.gz", "rt",
                   encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    seen = {r["channel_canonical"]: r["channel_reviewed"] for r in rows}
    for channel, flag in reviewed.items():
        if channel in seen:
            assert seen[channel] == ("true" if flag else "false"), channel


def test_series_key_is_summation_safe():
    from migration_parser.series import SERIES_KEY_FIELDS, series_key
    with (MIGRATION_DIR / "series.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows and "series_key" in rows[0]
    groups: dict[str, dict] = {}
    seen: dict[str, set] = {}
    for r in rows:
        assert r["series_key"] == series_key(r)
        key = r["series_key"]
        for fld in ("metric", "dimension", "unit", "year_basis", "gender", "note"):
            groups.setdefault(key, {}).setdefault(fld, set()).add(r[fld])
        # A summation-safe key must not repeat the row identity: two rows with
        # the same (name, fiscal_year, gender) inside one key would be silently
        # double-counted by a naive in-key sum (regression for the DATASET 7
        # cause-of-death tables, whose causes collided before `note` was keyed).
        ident = (r["name"], r["fiscal_year"], r["gender"])
        assert ident not in seen.setdefault(key, set()), f"{key}: duplicate {ident}"
        seen[key].add(ident)
    # every summation key is single-valued in the additive-relevant fields
    for key, cols in groups.items():
        for fld, vals in cols.items():
            assert len(vals) == 1, f"{key}: {fld}={vals}"
    # and no key omits a field required by SERIES_KEY_FIELDS
    assert set(SERIES_KEY_FIELDS) == {
        "report", "source_page", "caption", "metric", "dimension",
        "unit", "year_basis", "gender", "note"}


def test_source_attestation_shape():
    from migration_parser.scripts import cmd_provenance as prov
    att = json.loads(prov.ATTESTATION.read_text())
    docs = att["docs"]
    assert docs, "attestation has no docs"
    for d in docs:
        if d.get("missing_cached"):
            continue
        assert d["page_count"] > 0
        assert len(d["page_hashes"]) == d["page_count"]
        assert len(d["text_sha256"]) == 64
        assert d.get("pdf_sha256") and len(d["pdf_sha256"]) == 64


def test_manifest_pdf_hashes_are_recorded():
    manifest = json.loads(MIGRATION_MANIFEST.read_text())
    hashed = [e for e in manifest if e.get("pdf_sha256")]
    assert hashed, "no manifest entries carry a pdf_sha256"
    for e in hashed:
        assert len(e["pdf_sha256"]) == 64
        assert e.get("pdf_bytes", 0) > 1000


def test_driftcheck_clean_when_cached_hashes_match(tmp_path, monkeypatch):
    import hashlib

    from migration_parser.scripts import cmd_driftcheck, cmd_process

    cached = tmp_path / "001_123.pdf"
    cached.write_bytes(b"%PDF-1.4\nfixture\n")
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    entry = {
        "serial": 1,
        "title": "fixture",
        "pdf_url": "https://example.test/123.pdf",
        "pdf_sha256": digest,
    }
    monkeypatch.setattr(cmd_process, "load_manifest", lambda: [entry])
    monkeypatch.setattr(cmd_process, "pdf_path", lambda entry: cached)
    monkeypatch.setattr(cmd_driftcheck, "MIGRATION_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        cmd_driftcheck, "ARCHIVE_MANIFEST", tmp_path / "missing-archive.json")

    assert cmd_driftcheck.main([]) == 0
    out = json.loads((tmp_path / "drift.json").read_text())
    assert out["checked"] == 1
    assert out["drift"] == []


# --- archive backfill: family (a) monthly country × period-scope M/F/T ---

from migration_parser import historical  # noqa: E402
from migration_parser.historical import (  # noqa: E402
    HistDoc,
    HistRow,
    _check_additivity,
    _country_name,
    _is_gender_cell,
    _is_scope_word,
    _num,
    _table_layout,
    _validate,
    parse_report_month,
)
from migration_parser.model import DocMeta  # noqa: E402

# Preeti-codepoint header labels (these decode to the scope words below).
_PREV = "cf=j= d;fGt;Ddsf] hDdf"        # आ.व. मसान्तसम्मको जम्मा
_MONTH = "sflt{s dlxgfsf] hDdf"          # कार्तिक महिनाको जम्मा
_CUM = "cf=a= sflt{s d;fGt;Ddsf] hDdf"   # आ.ब. कार्तिक मसान्तसम्मको जम्मा


def test_preeti_scope_header_vectors_decode():
    assert _is_scope_word(_PREV) and _is_scope_word(_CUM)
    assert _is_scope_word(_MONTH)
    assert not _is_scope_word("Bahrain")


def test_gender_cell_recognises_preeti_mft():
    assert _is_gender_cell("k?if")
    assert _is_gender_cell("dlxnf")
    assert _is_gender_cell("hDdf")
    assert not _is_gender_cell("Bahrain")


def test_table_layout_family_a():
    row0 = ["क्र", "मुलुक", _PREV, "", "", _MONTH, "", "", _CUM, "", ""]
    row1 = ["", "", "k?if", "dlxnf", "hDdf",
            "k?if", "dlxnf", "hDdf", "k?if", "dlxnf", "hDdf"]
    row2 = ["1", "Bahrain", "1532", "47", "1579",
            "798", "20", "818", "2330", "67", "2397"]
    lay = _table_layout([row0, row1, row2])
    assert lay is not None
    data_start, b0, labels = lay
    assert (data_start, b0) == (2, 2)
    assert "महिना" in labels[1] and "मसान्त" in labels[0]


def test_table_layout_rejects_non_family():
    row0 = ["S.N.", "Country", "Total", "", "", "Total", "", ""]
    row1 = ["", "", "k?if", "dlxnf", "hDdf", "k?if", "dlxnf", "hDdf"]
    assert _table_layout([row0, row1]) is None


def test_table_layout_detects_second_block_offset():
    # 12-col institutional variant: M/F/T blocks start at col 3 (not 2).
    row0 = ["क्र", "मुलुक", "किसिम", _PREV, "", "", _MONTH, "", "",
            _CUM, "", ""]
    row1 = ["", "", "", "k?if", "dlxnf", "hDdf",
            "k?if", "dlxnf", "hDdf", "k?if", "dlxnf", "hDdf"]
    lay = _table_layout([row0, row1])
    assert lay is not None and lay[1] == 3


def test_parse_report_month():
    period, month = parse_report_month([_decode_lbl(_PREV), "०६९ कार्तिक महिनाको जम्मा"])
    assert period == "2069 कार्तिक"
    assert month == "कार्तिक"
    assert parse_report_month(["Bahrain", "no month here"]) == ("", "")


def test_parse_report_month_fiscal_year_scope():
    # "मसान्त" scope headers carry no "महिना"; report month = last label.
    labels = [
        "आ.व.०७१/७२ को चैत मसान्तसम्मको जम्मा",
        "आ.व.०७१/७२ को बैशाख मसान्तको जम्मा",
        "आ.व.०७१/७२ को बैशाख मसान्तसम्मको जम्मा",
    ]
    # Baishakh (month 1) of FY2071/72 falls in BS calendar year 2072.
    assert parse_report_month(labels) == ("2072 बैशाख", "बैशाख")
    # Falgun (month 11) stays in the fiscal start year; broken "फागन ु" alias.
    assert parse_report_month(
        ["आ.व.०७०/७१ को माघ मसान्तसम्मको जम्मा",
         "आ.व.०७०/७१ को फागन ु मसान्तको जम्मा",
         "आ.व.०७०/७१ को फागन ु मसान्तसम्मको जम्मा"]) == ("2070 फागुन", "फागुन")


def _decode_lbl(raw):
    from migration_parser import preeti
    return preeti.decode(raw)


def test_historical_num_and_country_name():
    assert _num("1,532") == 1532
    assert _num("") == 0
    assert _num(" 47 ") == 47
    assert _country_name("1", "Bahrain") == ("1", "Bahrain")
    assert _country_name("", "Afghanistan") == ("", "Afghanistan")
    # Preeti name in col-0 (no Latin col-1) falls back to decode.
    sn, np = _country_name("sf]l/of", "")
    assert sn == "" and np == "कोरिया"


def test_validate_flags_math_and_totals():
    meta = DocMeta(doc_id="x", filename="x.pdf", period_bs="2069 कार्तिक")
    rows = [
        HistRow("Bahrain", "month", 10, 2, 12),
        HistRow("Bahrain", "cumulative", 30, 5, 35),
        HistRow("Bahrain", "previous_cumulative", 20, 3, 23),
        HistRow("Qatar", "month", 5, 1, 6),
        HistRow("Qatar", "cumulative", 15, 2, 17),
        HistRow("Qatar", "previous_cumulative", 10, 1, 11),
    ]
    doc = HistDoc(meta=meta, rows=list(rows),
                  totals={"month": (15, 3, 18), "cumulative": (45, 7, 52)})
    assert _validate(doc) == []
    assert not doc.warnings  # 20+10==30, 10+5==15 etc.

    rows[0].total = 99  # break M+F==T and month total
    doc2 = HistDoc(meta=meta, rows=list(rows),
                   totals={"month": (15, 3, 18)})
    problems = _validate(doc2)
    assert any("M+F != T" in p for p in problems)
    assert any("month detail sum" in p for p in problems)


def test_validate_warns_on_source_cumulative_inconsistency():
    meta = DocMeta(doc_id="x", filename="x.pdf")
    doc = HistDoc(
        meta=meta,
        rows=[HistRow("Bahrain", "previous_cumulative", 20, 3, 23)],
        totals={"previous_cumulative": (999, 9, 1008)},
    )
    assert _validate(doc) == []
    assert any("source total inconsistent" in w for w in doc.warnings)


def test_additivity_warning():
    meta = DocMeta(doc_id="x", filename="x.pdf")
    doc = HistDoc(meta=meta, rows=[
        HistRow("Bahrain", "previous_cumulative", 1, 0, 1),
        HistRow("Bahrain", "month", 1, 0, 1),
        HistRow("Bahrain", "cumulative", 5, 0, 5),
    ])
    _check_additivity(doc)
    assert any("previous+month != cumulative" in w for w in doc.warnings)


def _sample(name):
    import os
    d = os.environ.get("MIGRATION_BACKFILL_SAMPLES", "/tmp/opencode/backfill")
    return Path(d) / name


@pytest.mark.skipif(not _sample("monthly_2069_kartik.pdf").exists(),
                    reason="archive backfill sample PDFs not available")
def test_extract_monthly_real_sample():
    # Family (a) is the 12-col labour-approval table (b0=3), split into
    # institutional / individual channels.
    doc = historical.extract_monthly(str(_sample("monthly_2069_kartik.pdf")))
    assert doc.ok
    assert doc.meta.period_bs == "2069 कार्तिक"
    assert len({r.country for r in doc.rows}) == 128
    assert {r.approval_type for r in doc.rows} == {"institutional", "individual"}
    assert all(r.male + r.female == r.total for r in doc.rows)
    assert all(r.scope in historical.SCOPES for r in doc.rows)


# --- archive backfill: resolve/fetch selection + period parsing ---

from migration_parser.scripts import cmd_backfill as backfill  # noqa: E402


def test_monthly_period_parsing():
    assert backfill._monthly_period("final-app-Kartik-2067.pdf") == (2067, 7)
    assert backfill._monthly_period(
        "२०६९_कार्तिक_महिनाको_प्रगति_विवरण.pdf") == (2069, 7)
    assert backfill._monthly_period(
        "monthly report of shrawan-2069_20120823122613.pdf") == (2069, 4)
    assert backfill._monthly_period("Monthly Report of  Bhandra-2068.pdf") == (2068, 5)


def test_monthly_period_excludes_other_products():
    assert backfill._monthly_period(
        "26Monthly Report of Ashwin -2067 (Sushashan Format).pdf") is None
    assert backfill._monthly_period("final-app-Kartik-2067 (Sastha & Ujuri).pdf") is None
    assert backfill._monthly_period("Final Data of 2050_51 to 2067_68.pdf") is None
    # Bare-month filenames (no year token) are admitted with an unknown year;
    # the extractor's verifier rejects them downstream if they are not family (a).
    assert backfill._monthly_period("kartik.pdf") == (None, 7)
    assert backfill._monthly_period("Push Final Report_20140130093447.pdf") == (None, 9)


def test_period_from_filename():
    assert backfill._period_from_filename("022_2070_Bhadra.pdf") == "2070 Bhadra"
    assert backfill._period_from_filename("012_2069_Shrawan.pdf") == "2069 Shrawan"
    assert backfill._period_from_filename("weird.pdf") == ""


def test_histdoc_verified_flag():
    meta = DocMeta(doc_id="x", filename="x.pdf")
    good = HistDoc(meta=meta, rows=[HistRow("Bahrain", "month", 1, 0, 1)])
    assert good.verified
    bad = HistDoc(meta=meta, rows=[HistRow("Bahrain", "month", 1, 0, 9)])
    bad.problems.extend(_validate(bad))
    assert not bad.verified
    assert not HistDoc(meta=meta).verified


@pytest.mark.skipif(not backfill.ARCHIVE_INVENTORY.exists(),
                    reason="Wayback inventory not available")
def test_resolve_candidates_shape():
    entries = backfill.resolve_candidates()
    assert entries, "no candidates resolved"
    for e in entries:
        assert e["serial"] >= 1
        assert e["wayback_url"].startswith("https://web.archive.org/web/")
        assert e["status"] == "pending"
        head = e["period_bs"].split()[0]
        assert head.startswith("20") or head == "unknown"
    periods = [(e["period_bs"]) for e in entries]
    assert len(periods) == len(set(periods)), "duplicate (year, month) candidates"


# --- archive panel: dedup of mismatched Wayback captures + gz schema ---

from migration_parser.scripts import cmd_archive_panel as apanel  # noqa: E402
from migration_parser import historical_new as hnew  # noqa: E402
from migration_parser import paths as mpaths  # noqa: E402


def _pair(serial, header, period):
    return ({"serial": serial, "period_bs": period, "wayback_url": ""},
            {"header_period_bs": header, "period_bs": period})


def test_archive_panel_pick_prefers_lowest_serial():
    keep, drop = apanel._pick(_pair(22, "", "2070 Bhadra"),
                              _pair(19, "2069 Chaitra", "2069 Chaitra"))
    assert keep[0]["serial"] == 19
    assert drop[0]["serial"] == 22


def test_archive_panel_pick_header_disagreement_overrides_serial():
    mismatched = _pair(19, "2069 Chaitra", "2070 Bhadra")
    agrees = _pair(22, "", "2070 Bhadra")
    keep, drop = apanel._pick(mismatched, agrees)
    assert keep[0]["serial"] == 22
    assert drop[0]["serial"] == 19


def test_archive_panel_gz_schema_and_dedup():
    if not mpaths.MIGRATION_ARCHIVE_PANEL.exists():
        pytest.skip("archive panel not built")
    if not mpaths.MIGRATION_ARCHIVE_UNRESOLVED.exists():
        pytest.skip("archive unresolved panel not built")
    import gzip as _gz
    import csv as _csv
    import json as _json
    with _gz.open(mpaths.MIGRATION_ARCHIVE_PANEL, "rt") as f:
        rows = list(_csv.DictReader(f))
    with _gz.open(mpaths.MIGRATION_ARCHIVE_UNRESOLVED, "rt") as f:
        unresolved = list(_csv.DictReader(f))
    assert rows and unresolved
    assert list(rows[0].keys()) == mpaths.ARCHIVE_PANEL_COLUMNS
    assert list(unresolved[0].keys()) == mpaths.ARCHIVE_PANEL_COLUMNS
    assert {r["source_kind"] for r in rows} == {"archive_org"}
    assert {r["verified"] for r in rows} == {"True"}
    assert {r["entity_resolved"] for r in rows} == {"True"}
    assert {r["analysis_safe"] for r in rows} == {"True"}
    assert {r["entity_resolved"] for r in unresolved} == {"False"}
    assert {r["analysis_safe"] for r in unresolved} == {"False"}
    shas = {r["source_pdf_sha256"] for r in rows}
    assert len(shas) == len({r["doc_id"] for r in rows}), "duplicate content not deduped"
    assert {r["scope"] for r in rows} == {
        "previous_cumulative", "month", "cumulative",
        "pre_permission", "final_approved"}
    assert {r["scope_class"] for r in rows} == {
        "prior_ytd", "window", "ytd", "pre_approval", "final_approval"}
    assert {r["granularity"] for r in rows} == {"month"}
    assert {r["approval_type"] for r in rows} == {"institutional", "individual"}
    assert {r["entry_type"] for r in rows} == {"", "re_entry", "new", "legalization"}
    assert all(r["name_canonical"] for r in rows)
    assert all(r["iso3"] for r in rows)
    meta = _json.loads(mpaths.MIGRATION_ARCHIVE_BUILD.read_text())
    assert meta["n_rows"] == len(rows)
    assert meta["n_unresolved"] == len(unresolved)
    assert meta["n_rows_all"] == len(rows) + len(unresolved)
    assert meta["n_analysis_safe"] == len(rows)


def test_scope_class_mapping():
    from migration_parser import historical
    assert historical.SCOPE_CLASS == {
        "previous_cumulative": "prior_ytd", "month": "window", "cumulative": "ytd",
        "pre_permission": "pre_approval", "final_approved": "final_approval"}


def test_channels_channel_map_is_explicit_tbd():
    from migration_parser import normalize
    cm = normalize.channel_map()
    assert cm.get("status") == "TBD"
    assert "individual" in cm and "institutional" in cm
    assert cm["institutional"] is None and cm["individual"] is None


def test_archive_panel_catalog_agreement_and_month_parser():
    mismatched = _pair(7, "2070 मंसिर", "unknown Poush")
    assert apanel._period_month("unknown Poush") == 9
    assert apanel._agrees(mismatched) is False
    assert apanel._agrees(_pair(22, "", "2070 Bhadra")) is True


def test_archive_panel_period_key_normalises_scripts():
    assert apanel._period_key("2069 Shrawan") == (2069, 4)
    assert apanel._period_key("2069 श्रावण") == (2069, 4)
    assert apanel._period_key("2070 मंसिर") == (2070, 8)
    assert apanel._period_key("") is None
    assert apanel._period_key("kartik") is None


# --- newer-stage archive template (BS 2073-2075) ---

def _new_doc():
    from migration_parser.historical import HistDoc
    return HistDoc(meta=DocMeta(filename="synthetic.pdf"))


def test_new_template_entry_type_detection():
    assert hnew._entry_type("k'gM >d :jLs[lt") == "re_entry"
    assert hnew._entry_type("gof“ >d :jLs[lt") == "new"
    assert hnew._entry_type("JolQmut ?kdf j}Bflgs/0f") == "legalization"
    assert hnew.section_of("JolQmx?sf] ;+VofTds ljj/0f k'gM >d :jLs[lt") == (
        "individual", "re_entry")


def test_new_template_header_kinds():
    five = [["SN", "Country", "Male", "Female", "Total"]]
    eight = [["S.N.", "Country", "Men", "Women", "Total",
              "Men", "Women", "Total"]]
    fourteen = [["S. No.", "Country", "Renew Entry", "None", "None",
                 "New Entry", "None", "None", "Legalized Entry", "None",
                 "None", "Total Men", "Total Women", "Total"]]
    assert hnew._header_kind(five) == "country_single"
    assert hnew._header_kind(eight) == "country_two"
    assert hnew._header_kind(fourteen) == "country_multi"


def test_new_template_14col_groups_are_entry_types_not_scopes():
    rows = [
        ["S. No.", "Country", "Renew Entry", "None", "None",
         "New Entry", "None", "None", "Legalized Entry", "None", "None",
         "Total Men", "Total Women", "Total"],
        ["1", "Nepal", "1", "2", "3", "4", "5", "9",
         "6", "7", "13", "11", "14", "25"],
    ]
    out = _new_doc()
    assert hnew._parse_country_table(out, rows, ("individual", ""), 1,
                                     "country_multi")
    assert {r.scope for r in out.rows} == {"final_approved"}
    assert {r.entry_type for r in out.rows} == set(hnew.ENTRY_TYPES)
    by_type = {r.entry_type: (r.male, r.female) for r in out.rows}
    assert by_type == {"re_entry": (1, 2), "new": (4, 5),
                       "legalization": (6, 7)}
