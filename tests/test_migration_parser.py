"""Tests for migration_parser — model templates, verification, periods."""

from migration_parser.model import DocMeta, ExtractResult, WideRow, channels_for
from migration_parser.parser import melt
from migration_parser.periods import (
    classify_doc_type,
    parse_ad_window,
    parse_bs_period,
)
from migration_parser.series import (
    classify_metric,
    extract_year_matrix,
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


def test_extract_year_matrix_rejects_crosstab():
    rows = [
        ["Country", "2008/09", "2009/10"],
        ["Malaysia", "1", "2"],
        ["Malaysia", "3", "4"],  # duplicate name×year → cross-tab, not a series
        ["Qatar", "5", "6"],
    ]
    assert extract_year_matrix(rows, "Table", 1, "r") == []
