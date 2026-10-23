"""Tests for redbook_parser.loader — validated cidmap store load."""

import json
from pathlib import Path

import pytest

from redbook_parser.loader import load_store


@pytest.fixture
def store_path():
    """Return the path to the real cidmap store."""
    return Path(__file__).parents[1] / "cidmap" / "data" / "cid_mappings.json"


class TestLoadStore:
    def test_loads_real_store(self, store_path):
        approved, rejections = load_store(store_path)
        assert isinstance(approved, dict)
        assert isinstance(rejections, dict)
        data = json.loads(store_path.read_text(encoding="utf-8"))
        total = len(approved) + sum(len(v) for v in rejections.values())
        assert total == len(data["cids"])

    def test_approved_are_single_devanagari(self, store_path):
        approved, _ = load_store(store_path)
        for cid, value in approved.items():
            assert len(value) == 1, f"cid {cid}: value {value!r} is not single char"
            assert 0x0900 <= ord(value) <= 0x097F, (
                f"cid {cid}: value {value!r} not Devanagari")

    def test_clusters_rejected(self, store_path):
        _, rejections = load_store(store_path)
        cluster_cids = {e["cid"] for e in rejections.get("not_single_devanagari", [])}
        # Multi-char cluster values that the derive tool produced.
        for cid in (3, 4, 13, 17, 18, 22, 31, 36, 39, 48, 49, 50,
                    67, 71, 73, 83, 85, 87, 88, 91, 94, 97):
            assert cid in cluster_cids, f"cid {cid} should be rejected as cluster"

    def test_legacy_cids_rejected(self, store_path):
        _, rejections = load_store(store_path)
        legacy_cids = {e["cid"] for e in rejections.get("in_legacy_cid_char_map", [])}
        # Single-char + in CID_CHAR_MAP: 14 ('व'), 33 ('ह'), 66 ('थ'), 70 ('आ').
        for cid in (14, 33, 66, 70):
            assert cid in legacy_cids, f"cid {cid} should be rejected (in CID_CHAR_MAP)"

    def test_single_devanagari_approved(self, store_path):
        approved, _ = load_store(store_path)
        # Single-char, non-legacy, non-artifact entries.
        for cid in (43, 56, 57, 64, 74, 81, 82, 84, 95, 98):
            assert cid in approved, f"cid {cid} should be approved"

    def test_approved_count(self, store_path):
        approved, _ = load_store(store_path)
        # 10 single-char entries approved; CID 1 is font-scoped, not a fallback.
        assert len(approved) == 10

    def test_rejection_report_structure(self, store_path):
        _, rejections = load_store(store_path)
        for reason, entries in rejections.items():
            assert isinstance(entries, list)
            for e in entries:
                assert "cid" in e
                assert "value" in e
                assert "source" in e

    def test_empty_store_file(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text('{"cids": {}, "fonts": {}, "meta": {}, "schema_version": 1}')
        approved, rejections = load_store(p)
        assert approved == {}
        assert rejections == {}
