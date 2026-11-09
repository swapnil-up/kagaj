from __future__ import annotations

from govweb import entities as e


def test_classify_description_maps_government_phrases():
    assert e.classify_description("government ministry in Nepal") == ("ministry", "central")
    assert e.classify_description("province of Nepal") == ("province", "provincial")
    assert e.classify_description("district court of Nepal") == ("court", "central")
    assert e.classify_description("municipality in Kaski") == ("local_level", "local")


def test_classify_description_leaves_non_government_text_unknown():
    assert e.classify_description("football club in Kathmandu") == ("unknown", "unknown")
    assert e.classify_description("") == ("unknown", "unknown")
    assert e.classify_description(None) == ("unknown", "unknown")


def test_apex_of_reduces_subdomains_to_three_labels():
    assert e.apex_of("2016.presidentofnepal.gov.np") == "presidentofnepal.gov.np"
    assert e.apex_of("mof.gov.np") == "mof.gov.np"
    assert e.apex_of("www.mof.gov.np") == "mof.gov.np"


def test_local_level_entity_inherits_its_attribution():
    attribution = {
        "dhorpatanmun.gov.np": {
            "hostname": "dhorpatanmun.gov.np",
            "local_level_id": "3",
            "local_level_name": "Dhorpatan Municipality",
            "district": "Baglung",
            "method": "localbody_directory",
            "confidence": "high",
            "evidence_url": "http://eoffice.mahalaxmimun.gov.np/dcc-localbody-list",
        }
    }
    record = e.classify_apex("dhorpatanmun.gov.np", attribution=attribution, wikidata_by_host={}, seed={})
    assert record["owner_type"] == "local_level"
    assert record["owner_scope"] == "local"
    assert record["local_level_id"] == "3"
    assert record["method"] == "attribution:localbody_directory"
    assert record["evidence_url"]


def test_unknown_apex_is_never_guessed():
    record = e.classify_apex("mysteryoffice.gov.np", attribution={}, wikidata_by_host={}, seed={})
    assert record["owner_type"] == "unknown"
    assert record["method"] == "unclassified"
    assert record["confidence"] == "none"
    assert record["evidence_url"] == ""


def test_wikidata_classifies_only_when_a_type_is_derivable():
    wikidata = {
        "moe.gov.np": [
            {
                "qid": "Q1",
                "label": "Ministry of Education",
                "description": "government ministry in Nepal",
                "website": "https://moe.gov.np",
                "district": None,
            }
        ],
        "mystery.gov.np": [
            {
                "qid": "Q2",
                "label": "Mystery",
                "description": "football club",
                "website": "https://mystery.gov.np",
                "district": None,
            }
        ],
    }
    ministry = e.classify_apex("moe.gov.np", attribution={}, wikidata_by_host=wikidata, seed={})
    assert ministry["owner_type"] == "ministry"
    assert ministry["qid"] == "Q1"
    unknown = e.classify_apex("mystery.gov.np", attribution={}, wikidata_by_host=wikidata, seed={})
    assert unknown["owner_type"] == "unknown"


def test_seed_overrides_wikidata_and_requires_evidence_field():
    seed = {
        "special.gov.np": {
            "owner_label": "Special Body",
            "owner_type": "commission",
            "confidence": "high",
            "evidence_note": "curated",
        }
    }
    record = e.classify_apex("special.gov.np", attribution={}, wikidata_by_host={}, seed=seed)
    assert record["owner_type"] == "commission"
    assert record["owner_scope"] == "central"
    assert record["method"] == "manual"


def test_classify_counts_reconcile():
    attribution = {
        "gaurmun.gov.np": {
            "local_level_id": "1",
            "local_level_name": "Gaur Municipality",
            "district": "Rautahat",
            "method": "localbody_directory",
            "confidence": "high",
            "evidence_url": "https://example.test",
        }
    }
    document = e.classify(
        ["gaurmun.gov.np", "www.gaurmun.gov.np", "mof.gov.np", "unknown.gov.np"],
        attribution=attribution,
        wikidata_by_host={},
        seed={},
        generated_at="2026-11-09",
    )
    assert document["apex_hostnames"] == 3
    assert document["by_type"]["local_level"] == 1
    assert document["by_type"]["unknown"] == 2
    assert sum(document["by_type"].values()) == document["apex_hostnames"]
    assert document["classified"] == 1
