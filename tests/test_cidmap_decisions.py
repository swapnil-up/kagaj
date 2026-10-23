from cidmap.decisions import apply_decisions, decision_fields
from cidmap.mappings import empty_store, get_value


FONT = "ABCDEF+Kalimati-1"


def test_neutral_fields_are_accepted():
    font, cid, value, undecodable, inconsistent, note = decision_fields({
        "key": f"{FONT}\u25712",
        "value": "व्यय",
        "undecodable": False,
        "note": "checked",
        "data": {"font_id": FONT, "cid": 2},
    })
    assert (font, cid, value, undecodable, inconsistent, note) == (
        FONT, 2, "व्यय", False, False, "checked")


def test_apply_decisions_writes_font_scoped_value():
    store = empty_store()
    result = apply_decisions(store, [{
        "key": f"{FONT}\u25712",
        "value": "व्यय",
        "data": {"font_id": FONT, "cid": 2, "source": "review"},
    }])
    assert result.ok
    assert result.values == 1
    assert get_value(store, FONT, 2) == "व्यय"
    assert store["cids"][2]["_meta"]["source"] == "review"


def test_apply_decisions_does_not_overwrite():
    store = empty_store()
    store["fonts"][FONT] = {2: "क"}
    store["cids"][2] = {FONT: "क"}
    result = apply_decisions(store, [{
        "key": f"{FONT}\u25712",
        "value": "ख",
        "data": {"font_id": FONT, "cid": 2},
    }])
    assert not result.ok
    assert get_value(store, FONT, 2) == "क"
