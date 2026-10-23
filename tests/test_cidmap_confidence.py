from types import SimpleNamespace

from cidmap.confidence import build_candidate, format_candidates


FONT = "KLMNGO+Kalimati"


def _entry(*, value="ि", support=2, status="confirmed", source="store",
           font=FONT, cid=7):
    observations = []
    if source:
        observations.append({
            "doc_sha256": "a" * 64,
            "font_id": font,
            "cid": cid,
            "value": value,
            "source": source,
            "evidence": [],
            "observed_at": "2026-01-01T00:00:00+00:00",
        })
    return {
        "family_hash": "b" * 64,
        "outline_hash": "c" * 64,
        "base_font": "Kalimati",
        "value": value,
        "values": [value],
        "status": status,
        "support": support,
        "documents": ["a" * 64],
        "observations": observations,
        "conflicts": [],
    }


def _bundle(entry):
    return {"entry": entry}


def test_confirmed_registry_promotes():
    candidate = build_candidate(FONT, 7, _bundle(_entry()))
    assert candidate.promotable
    assert candidate.value == "ि"
    assert candidate.score >= 0.7


def test_provisional_single_document_is_blocked():
    candidate = build_candidate(
        FONT, 7, _bundle(_entry(support=1, status="provisional")))
    assert not candidate.promotable
    assert any("second independent document" in b for b in candidate.blockers)


def test_exact_review_observation_allows_one_document():
    candidate = build_candidate(
        FONT, 7,
        _bundle(_entry(support=1, status="provisional", source="review")))
    assert candidate.promotable
    assert any("reviewer-confirmed" in reason for reason in candidate.reasons)


def test_review_of_another_glyph_does_not_authorize_this_one():
    candidate = build_candidate(
        FONT, 8,
        _bundle(_entry(support=1, status="provisional", source="review")))
    assert not candidate.promotable


def test_conflict_blocks_promotion():
    candidate = build_candidate(
        FONT, 7, _bundle(_entry(value="", status="conflict")))
    assert not candidate.promotable
    assert "registry conflict" in candidate.blockers


def test_shape_run_must_agree():
    inference = SimpleNamespace(value="व्")
    candidate = build_candidate(FONT, 7, _bundle(_entry()), inference=inference)
    assert not candidate.promotable
    assert any("shape-run disagrees" in blocker for blocker in candidate.blockers)


def test_existing_mapping_is_never_overwritten():
    candidate = build_candidate(FONT, 7, _bundle(_entry()), existing="क")
    assert not candidate.promotable
    assert any("already mapped" in blocker for blocker in candidate.blockers)


def test_invalid_value_is_blocked():
    candidate = build_candidate(FONT, 7, _bundle(_entry(value="िि")))
    assert not candidate.promotable
    assert "invalid Devanagari value" in candidate.blockers


def test_candidate_decision_shape():
    candidate = build_candidate(FONT, 7, _bundle(_entry()))
    decision = candidate.decision()
    assert decision["key"] == f"{FONT}\u25717"
    assert decision["value"] == "ि"
    assert decision["data"]["source"] == "promote"


def test_format_candidates_reports_counts():
    candidate = build_candidate(FONT, 7, _bundle(_entry()))
    text = format_candidates([candidate])
    assert "Promotable: 1" in text
    assert "PROMOTE" in text
