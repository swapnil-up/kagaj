import json
from pathlib import Path

import pytest

from govweb.roster import (
    all_local_levels,
    by_district,
    by_province,
    counts,
    find_local_level,
    load_roster,
    normalize_name,
)
from govweb.roster_fetch import normalize_roster


FIXTURE = Path(__file__).parent / "fixtures" / "govweb" / "roster_sample.json"


@pytest.fixture

def roster():
    return load_roster(FIXTURE)


def test_fixture_load_and_all_local_levels(roster):
    assert len(all_local_levels(roster)) == 5
    assert all(record["municipality_id"] for record in roster)


def test_name_normalization_collapses_whitespace_and_case():
    assert normalize_name("  RURAL   Municipality  ") == "rural municipality"
    assert normalize_name("Biratnagar Metropolitan City") == (
        "biratnagar metropolitan city"
    )


def test_display_normalization_does_not_rewrite_words():
    payload = {
        "provinces": [
            {
                "id": 1,
                "name": " Province   One ",
                "districts": [
                    {
                        "id": 10,
                        "name": " District   One ",
                        "municipalities": [
                            {"id": 100, "name": " Rural   Municipality "}
                        ],
                    }
                ],
            }
        ],
        "reports": [],
        "fiscal_years": [],
    }
    records, provinces, districts = normalize_roster(payload)
    assert provinces == 1
    assert districts == 1
    assert records[0]["province"] == "Province One"
    assert records[0]["district"] == "District One"
    assert records[0]["name"] == "Rural Municipality"
    assert records[0]["normalized_name"] == "rural municipality"


def test_by_district_supports_name_and_stable_id(roster):
    assert [r["municipality_id"] for r in by_district(roster, "Morang")] == [
        "1001",
        "1002",
    ]
    assert len(by_district(roster, "101")) == 2
    assert by_district(roster, "Unknown") == []


def test_by_province_supports_name_and_stable_id(roster):
    assert len(by_province(roster, "Koshi Province")) == 3
    assert len(by_province(roster, "2")) == 2
    assert by_province(roster, "Unknown") == []


def test_counts_use_distinct_geographical_ids(roster):
    assert counts(roster) == {
        "province_count": 2,
        "district_count": 3,
        "municipality_count": 5,
    }


def test_find_local_level_is_case_and_whitespace_insensitive(roster):
    result = find_local_level(roster, " JANAKI  rural municipality ")
    assert len(result) == 1
    assert result[0]["municipality_id"] == "2002"


def test_load_roster_rejects_non_array(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_roster(path)


def test_normalize_roster_rejects_missing_provinces():
    with pytest.raises(ValueError, match="provinces list"):
        normalize_roster({"reports": [], "fiscal_years": []})
