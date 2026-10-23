import json

from cidmap import registry


FAMILY = "a" * 64
OUTLINE = "b" * 64
DOC1 = "c" * 64
DOC2 = "d" * 64


def _obs(*, family=FAMILY, outline=OUTLINE, value="ि", doc=DOC1,
         font="FONT", cid=1, source="store"):
    return {
        "family_hash": family,
        "outline_hash": outline,
        "value": value,
        "doc_sha256": doc,
        "font_id": font,
        "cid": cid,
        "base_font": "Kalimati",
        "source": source,
        "evidence": ["p1"],
    }


def test_same_document_is_idempotent():
    reg = registry.empty_registry()
    assert registry.observe(reg, _obs()) is True
    assert registry.observe(reg, _obs()) is False
    entry = registry.lookup(reg, FAMILY, OUTLINE)
    assert entry["support"] == 1
    assert len(entry["observations"]) == 1
    assert entry["status"] == "provisional"


def test_independent_documents_confirm_a_glyph():
    reg = registry.empty_registry()
    registry.observe(reg, _obs(doc=DOC1))
    registry.observe(reg, _obs(doc=DOC2, font="OTHER", cid=9))
    entry = registry.lookup(reg, FAMILY, OUTLINE)
    assert entry["support"] == 2
    assert entry["status"] == "confirmed"
    assert entry["value"] == "ि"


def test_review_source_confirms_one_document():
    reg = registry.empty_registry()
    registry.observe(reg, _obs(source="review"))
    entry = registry.lookup(reg, FAMILY, OUTLINE)
    assert entry["status"] == "confirmed"


def test_conflicting_values_are_frozen():
    reg = registry.empty_registry()
    registry.observe(reg, _obs(value="ि", doc=DOC1))
    registry.observe(reg, _obs(value="व्", doc=DOC2, cid=2))
    entry = registry.lookup(reg, FAMILY, OUTLINE)
    assert entry["status"] == "conflict"
    assert entry["value"] == ""
    assert entry["values"] == ["व्", "ि"]
    assert len(entry["conflicts"]) == 2


def test_different_font_families_do_not_merge():
    reg = registry.empty_registry()
    registry.observe(reg, _obs(family=FAMILY))
    registry.observe(reg, _obs(family="e" * 64, doc=DOC2))
    assert len(reg["glyphs"]) == 2
    assert registry.lookup(reg, FAMILY, OUTLINE)["support"] == 1
    assert registry.lookup(reg, "e" * 64, OUTLINE)["support"] == 1


def test_save_and_load_are_deterministic(tmp_path):
    reg = registry.empty_registry()
    registry.observe(reg, _obs(doc=DOC2, cid=9, font="B"))
    registry.observe(reg, _obs(doc=DOC1, cid=1, font="A"))
    path = tmp_path / "registry.json"
    registry.save(reg, path)
    first = path.read_text(encoding="utf-8")
    loaded = registry.load(path)
    registry.save(loaded, path)
    assert path.read_text(encoding="utf-8") == first
    saved = json.loads(first)
    assert saved["schema_version"] == registry.SCHEMA_VERSION
    assert saved["glyphs"]


def test_format_entry_marks_conflict():
    reg = registry.empty_registry()
    registry.observe(reg, _obs(value="ि", doc=DOC1))
    registry.observe(reg, _obs(value="व्", doc=DOC2, cid=2))
    text = registry.format_entry(registry.lookup(reg, FAMILY, OUTLINE))
    assert "(conflict)" in text
    assert "'व्'" in text and "'ि'" in text
