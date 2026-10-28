"""Coordinate and bbox tests for the shared review crop helper."""

from kagaj_core.review.crops import (
    _display_bbox,
    _map_rect,
    _text_bbox,
    sanitize_glyph_bbox,
)


class FakePage:
    def __init__(self, rect, rotation=0):
        self.rect = rect
        self.rotation = rotation


def test_map_rect_is_inverse_for_all_rotations():
    rect = (10.0, 20.0, 30.0, 40.0)
    for rotation in (0, 90, 180, 270):
        page = FakePage((0, 0, 200, 100), rotation)
        display = _display_bbox(page, rect)
        assert _text_bbox(page, display) == rect


def test_display_bbox_clips_nothing_but_maps_rotation():
    page = FakePage((0, 0, 200, 100), 90)
    assert _display_bbox(page, (10, 20, 30, 40)) == (160, 10, 180, 30)


def test_map_rect_normalizes_reversed_coordinates():
    assert _map_rect((30, 40, 10, 20), 200, 100, 0) == (10, 20, 30, 40)


def test_sanitize_expands_zero_width_glyph():
    page = FakePage((0, 0, 200, 100))
    bbox = sanitize_glyph_bbox(page, (10, 20, 10, 32), font_size=12)
    assert bbox[2] - bbox[0] >= 4.0
    assert bbox[3] - bbox[1] >= 10.0


def test_sanitize_keeps_normal_bbox():
    page = FakePage((0, 0, 200, 100))
    assert sanitize_glyph_bbox(page, (10, 20, 20, 32)) == (10, 20, 20, 32)


def test_sanitize_rejects_invalid_bbox():
    page = FakePage((0, 0, 200, 100))
    assert sanitize_glyph_bbox(page, None) is None
    assert sanitize_glyph_bbox(page, (float("nan"), 0, 1, 1)) is None
