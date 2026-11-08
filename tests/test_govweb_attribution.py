from __future__ import annotations

import json

from govweb import attribution as a


def _record(identifier: str, name: str, district: str, province: str = "Bagmati") -> dict:
    return {
        "municipality_id": identifier,
        "name": name,
        "district": district,
        "province": province,
    }


ROSTER = [
    _record("1", "Gaur Municipality", "Rautahat", "Madhesh"),
    _record("2", "Gauriganj Rural Municipality", "Jhapa", "Koshi"),
    _record("3", "Dhorpatan Municipality", "Baglung"),
    _record("4", "Barpak Sulikot Rural Municipality", "Gorkha"),
]


def test_normalize_name_drops_local_level_suffixes():
    assert a.normalize_name("Dhorpatan Municipality") == "dhorpatan"
    assert a.normalize_name("Barpak Sulikot Rural Municipality") == "barpak sulikot"


def test_hostname_from_url_strips_scheme_www_and_path():
    assert a.hostname_from_url("https://www.gaurmun.gov.np/en") == "gaurmun.gov.np"
    assert a.hostname_from_url("gaurmun.gov.np") == "gaurmun.gov.np"
    assert a.hostname_from_url("") == ""


def test_is_local_level_hostname_rejects_district_offices():
    assert a.is_local_level_hostname("gaurmun.gov.np") is True
    assert a.is_local_level_hostname("ddcbaglung.gov.np") is False
    assert a.is_local_level_hostname("example.com") is False


def test_directory_row_with_unrelated_hostname_is_rejected():
    row = {"serial": 1, "name_en": "Gaur Municipality", "website": "https://rajapurmun.gov.np"}
    by_district, by_name = a._roster_index(ROSTER)
    match = a.match_directory_row(row, by_name, ROSTER)
    assert match is not None
    record, _, _ = match
    assert a.hostname_matches_record(row["website"], record) is False


def test_attribute_accepts_corroborated_directory_rows_only():
    directory = [
        {"serial": 1, "name_en": "Dhorpatan Municipality", "website": "https://dhorpatanmun.gov.np", "wards": 9},
        {"serial": 2, "name_en": "Gaur Municipality", "website": "https://rajapurmun.gov.np", "wards": 9},
    ]
    document = a.attribute(
        ROSTER,
        wikidata=[],
        hostnames=[],
        directory=directory,
        adjudication={},
        decided_at="2026-11-06",
    )
    assert document["mapped_local_levels"] == 1
    assert document["records"][0]["hostname"] == "dhorpatanmun.gov.np"
    assert document["records"][0]["local_level_id"] == "3"
    assert document["records"][0]["method"] == "localbody_directory"
    assert document["records"][0]["evidence_url"].endswith("/dcc-localbody-list")
    assert document["unresolved_local_levels"] == 3


def test_one_hostname_is_never_owned_by_two_local_levels():
    directory = [
        {"serial": 1, "name_en": "Gaur Municipality", "website": "https://gaurmun.gov.np", "wards": 9},
    ]
    wikidata = [
        {
            "qid": "Q1",
            "label": "Gauriganj Rural Municipality",
            "description": "rural municipality in Jhapa",
            "website": "https://gaurmun.gov.np/",
            "district": "Jhapa",
        }
    ]
    document = a.attribute(
        ROSTER,
        wikidata=wikidata,
        hostnames=[],
        directory=directory,
        adjudication={},
        decided_at="2026-11-06",
    )
    hosts = [record["hostname"] for record in document["records"]]
    assert hosts.count("gaurmun.gov.np") == 1
    owners = {record["local_level_id"] for record in document["records"] if record["hostname"] == "gaurmun.gov.np"}
    assert owners == {"1"}


def test_blocked_province_slug_is_never_attributed():
    roster = [_record("1", "Koshi Rural Municipality", "Sunsari", "Koshi")]
    directory = [
        {"serial": 1, "name_en": "Koshi Rural Municipality", "website": "https://koshi.gov.np", "wards": 7}
    ]
    document = a.attribute(
        roster,
        wikidata=[],
        hostnames=["koshi.gov.np"],
        directory=directory,
        adjudication={},
        decided_at="2026-11-06",
    )
    assert document["mapped_local_levels"] == 0
    assert document["records"] == []
    assert document["unresolved_local_levels"] == 1


def test_adjudicated_records_are_excluded_from_the_denominator():
    adjudication = {"1": {"local_level_id": "1", "status": "superseded"}}
    document = a.attribute(
        ROSTER,
        wikidata=[],
        hostnames=[],
        directory=[],
        adjudication=adjudication,
        decided_at="2026-11-06",
    )
    assert document["roster_records"] == 4
    assert document["canonical_local_levels"] == 3
    assert document["excluded_records"] == 1
    assert "1" not in {record["local_level_id"] for record in document["unresolved"]}


def test_ct_slug_attribution_and_method_counts_reconcile():
    document = a.attribute(
        ROSTER,
        wikidata=[],
        hostnames=["dhorpatanmun.gov.np", "unrelated.gov.np"],
        directory=[],
        adjudication={},
        decided_at="2026-11-06",
    )
    methods = document["methods"]
    assert sum(methods.values()) == len(document["records"])
    assert methods == {"ct_hostname_slug": 1}
    assert document["coverage_percent"] == round(100.0 * 1 / 4, 2)


def test_slug_stems_strip_glued_type_and_district():
    assert "triveni" in a._slug_stems("trivenimunsalyan", "Salyan")
    assert "shuddhodhan" in a._slug_stems("shuddhodhanmunrupandehi", "Rupandehi")
    assert "kaligandaki" in a._slug_stems("kaligandakimungulmi", "Gulmi")


def test_tolerant_slug_match_accepts_transliteration_variants():
    assert a._name_slug_agrees("jaiminimun.gov.np", "Jaimuni Municipality", district="Baglung")
    assert a._name_slug_agrees("sunaryamun.gov.np", "Surnaya Rural Municipality", district="Baitadi")
    assert a._name_slug_agrees("talkotmun.gov.np", "Talakot Rural Municipality", district="Bajhang")


def test_generic_slug_does_not_corroborate_a_name():
    assert a._name_slug_agrees("kalikamun.gov.np", "Kalika Rural Municipality", district="Gulmi") is True
    assert a._name_slug_agrees("rainbowmun.gov.np", "Kalika Rural Municipality", district="Gulmi") is False


def test_district_in_hostname_requires_a_real_district_token():
    assert a._district_in_hostname("madimunchitwan.gov.np", "Chitwan") is True
    assert a._district_in_hostname("likhumunokhaldhunga.gov.np", "Okhaldhunga") is True
    assert a._district_in_hostname("gaurmun.gov.np", "Rautahat") is False


def test_same_name_rows_are_split_by_the_district_named_in_the_hostname():
    roster = [
        _record("1", "Likhu Rural Municipality", "Nuwakot"),
        _record("2", "Likhu Rural Municipality", "Okhaldhunga"),
    ]
    row = {"serial": 1, "name_en": "Likhu Rural Municipality", "website": "https://likhumunokhaldhunga.gov.np"}
    _, by_name = a._roster_index(roster)
    match = a.match_directory_row(row, by_name, roster)
    assert match is not None
    assert match[0]["municipality_id"] == "2"


def test_ambiguous_same_name_row_without_corroboration_is_dropped():
    roster = [
        _record("1", "Aurahi Rural Municipality", "Siraha"),
        _record("2", "Aurahi Rural Municipality", "Dhanusa"),
        _record("3", "Aurahi Municipality", "Mahottari"),
    ]
    row = {"serial": 1, "name_en": "Aurahi Rural Municipality", "website": "https://example.gov.np"}
    _, by_name = a._roster_index(roster)
    assert a.match_directory_row(row, by_name, roster) is None


def test_overrides_reject_and_accept_links():
    roster = [_record("1", "Manara Sishawa Municipality", "Mahottari")]
    directory = [
        {
            "serial": 1,
            "name_en": "Manara Sishawa Municipality",
            "website": "https://manrashiswamun.gov.np",
        }
    ]
    overrides = {
        "reject": [{"local_level_id": "1", "hostname": "manrashiswamun.gov.np"}],
        "accept": [
            {
                "local_level_id": "1",
                "hostname": "manarashiswamun.gov.np",
                "confidence": "medium",
                "evidence_note": "Corrected spelling resolves; the directory hostname does not.",
            }
        ],
    }
    document = a.attribute(
        roster,
        wikidata=[],
        hostnames=["manrashiswamun.gov.np", "manarashiswamun.gov.np"],
        directory=directory,
        adjudication={},
        overrides=overrides,
        decided_at="2026-11-09",
    )
    hosts = [record["hostname"] for record in document["records"]]
    assert hosts == ["manarashiswamun.gov.np"]
    assert document["records"][0]["method"] == "manual"
    assert document["records"][0]["confidence"] == "medium"
    assert document["mapped_local_levels"] == 1


def test_overrides_reject_leaves_the_local_level_unresolved():
    roster = [_record("1", "Gaur Municipality", "Rautahat")]
    directory = [
        {"serial": 1, "name_en": "Gaur Municipality", "website": "https://gaurmun.gov.np"}
    ]
    overrides = {"reject": [{"local_level_id": "1", "hostname": "gaurmun.gov.np"}], "accept": []}
    document = a.attribute(
        roster,
        wikidata=[],
        hostnames=[],
        directory=directory,
        adjudication={},
        overrides=overrides,
        decided_at="2026-11-09",
    )
    assert document["records"] == []
    assert document["unresolved"][0]["local_level_id"] == "1"


def test_resolved_records_carry_evidence(tmp_path):
    document = a.attribute(
        ROSTER,
        wikidata=[],
        hostnames=["dhorpatanmun.gov.np"],
        directory=[],
        adjudication={},
        decided_at="2026-11-06",
    )
    for record in document["records"] + document["unresolved"]:
        assert record["method"]
        assert record["decided_at"] == "2026-11-06"
        assert "evidence_note" in record
    path = a.write_document(document, tmp_path)
    assert json.loads(path.read_text())["mapped_local_levels"] == 1
