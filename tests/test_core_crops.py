"""Tests for the shared PDF crop renderer."""

import subprocess
import sys
from pathlib import Path

import pytest

from kagaj_core.review import ReviewCrop
from kagaj_core.review import crops

ROOT = Path(__file__).resolve().parents[1]


class FakePage:
    def __init__(self, rect=(0, 0, 200, 100), rotation=0):
        self.rect = rect
        self.rotation = rotation


class FakeDoc:
    def __init__(self, pages):
        self.pages = pages

    def __getitem__(self, index):
        return self.pages[index]


@pytest.fixture
def calls(monkeypatch):
    captured = []

    def fake_render(page, rect, dpi, *, max_pixels):
        captured.append((page, rect, dpi, max_pixels))
        return f"data:image/png;base64,{len(captured)}"

    monkeypatch.setattr(crops, "_render_region", fake_render)
    return captured


def test_word_crop_clips_and_overlays_against_actual_image(calls):
    page = FakePage()
    crop = crops.render_review_crop(
        FakeDoc([page]),
        word=(1, (100, 50, 140, 70)),
        glyph=(1, (110, 55, 118, 65)),
    )

    assert isinstance(crop, ReviewCrop)
    assert crop.glyph == "data:image/png;base64,1"
    assert crop.word == "data:image/png;base64,2"
    assert calls[0][0] is page
    assert calls[1][0] is page
    assert calls[1][1] == (92.0, 42.0, 148.0, 78.0)
    assert calls[1][2] == crops.WORD_DPI
    assert 300 <= calls[0][2] <= 600
    assert crop.overlay == {
        "left": "32.14%", "top": "36.11%",
        "width": "14.29%", "height": "27.78%",
    }


def test_crop_at_page_edge_uses_clipped_rect(calls):
    crop = crops.render_review_crop(
        FakeDoc([FakePage((0, 0, 100, 100))]),
        word=(1, (-20, -10, 20, 10)),
        glyph=(1, (-10, -5, 10, 5)),
    )

    assert calls[1][1] == (0.0, 0.0, 28.0, 18.0)
    assert crop.overlay == {
        "left": "0.00%", "top": "0.00%",
        "width": "35.71%", "height": "27.78%",
    }


def test_word_and_glyph_can_live_on_different_pages(calls):
    pages = [FakePage(), FakePage()]
    crop = crops.render_review_crop(
        FakeDoc(pages),
        word=(2, (10, 10, 50, 30)),
        glyph=(1, (20, 20, 28, 30)),
    )

    assert [call[0] for call in calls] == pages
    assert crop.glyph and crop.word
    assert crop.overlay is None


def test_zero_width_glyph_box_is_expanded_before_rendering(calls):
    crop = crops.render_review_crop(
        FakeDoc([FakePage()]),
        word=(1, (40, 40, 80, 60)),
        glyph=(1, (50, 50, 50, 50)),
    )

    glyph_rect = calls[0][1]
    assert glyph_rect[2] > glyph_rect[0]
    assert glyph_rect[3] > glyph_rect[1]
    assert glyph_rect[0] < 50 < glyph_rect[2]
    assert glyph_rect[1] < 50 < glyph_rect[3]
    assert crop.glyph and crop.word


def test_word_only_and_glyph_only_are_valid(calls):
    doc = FakeDoc([FakePage()])
    word_only = crops.render_review_crop(doc, word=(1, (10, 10, 20, 20)))
    assert word_only.word and word_only.glyph is None
    assert len(calls) == 1

    calls.clear()
    glyph_only = crops.render_review_crop(doc, glyph=(1, (10, 10, 20, 20)))
    assert glyph_only.glyph and glyph_only.word is None
    assert len(calls) == 1


def test_glyph_failure_keeps_word_crop(monkeypatch):
    def render(page, rect, dpi, *, max_pixels):
        if not render.failed:
            render.failed = True
            raise RuntimeError("bad page")
        return "data:image/png;base64,WORD"

    render.failed = False
    monkeypatch.setattr(crops, "_render_region", render)

    crop = crops.render_review_crop(
        FakeDoc([FakePage()]),
        word=(1, (40, 40, 80, 60)),
        glyph=(1, (50, 50, 58, 60)),
    )

    assert crop.glyph is None
    assert crop.word == "data:image/png;base64,WORD"
    assert crop.overlay is not None


def test_word_failure_keeps_glyph_crop(monkeypatch):
    def render(page, rect, dpi, *, max_pixels):
        if not render.calls:
            render.calls += 1
            return "data:image/png;base64,GLYPH"
        raise RuntimeError("bad page")

    render.calls = 0
    monkeypatch.setattr(crops, "_render_region", render)

    crop = crops.render_review_crop(
        FakeDoc([FakePage()]),
        word=(1, (40, 40, 80, 60)),
        glyph=(1, (50, 50, 58, 60)),
    )

    assert crop.glyph == "data:image/png;base64,GLYPH"
    assert crop.word is None
    assert crop.overlay is None


def test_rotated_page_bboxes_are_mapped_to_display_space(calls):
    page = FakePage((0, 0, 100, 200), rotation=90)
    crop = crops.render_review_crop(
        FakeDoc([page]),
        word=(1, (20, 30, 60, 50)),
        glyph=(1, (30, 35, 38, 45)),
    )

    assert calls[1][1] == (42.0, 12.0, 78.0, 68.0)
    assert crop.overlay == {
        "left": "36.11%", "top": "32.14%",
        "width": "27.78%", "height": "14.29%",
    }


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotation_inverse_round_trips(rotation):
    rect = (0, 0, 200, 100) if rotation in (90, 270) else (0, 0, 100, 200)
    page = FakePage(rect, rotation=rotation)
    bbox = (20, 30, 60, 50)
    display = crops._display_bbox(page, bbox)
    assert crops._text_bbox(page, display) == bbox


@pytest.mark.parametrize("rotation,expected", [
    (0, (20, 30, 60, 50)),
    (90, (150, 20, 170, 60)),
    (180, (40, 150, 80, 170)),
    (270, (30, 40, 50, 80)),
])
def test_rotation_matrix_for_every_quarter_turn(rotation, expected):
    rect = (0, 0, 200, 100) if rotation in (90, 270) else (0, 0, 100, 200)
    page = FakePage(rect, rotation=rotation)
    assert crops._display_bbox(page, (20, 30, 60, 50)) == expected


def test_dpi_is_capped_for_large_crops():
    dpi = crops._limit_dpi((0, 0, 2000, 2000), 600, 1_000_000)
    pixels = (2000 * dpi / 72.0) ** 2
    assert dpi < 600
    assert pixels <= 1_000_000 * 1.01


def test_missing_bboxes_return_empty_crop(calls):
    crop = crops.render_review_crop(FakeDoc([FakePage()]))
    assert crop == ReviewCrop()
    assert calls == []


def test_crop_module_import_is_lazy():
    code = (
        "import sys; import kagaj_core.review.crops; "
        "assert 'fitz' not in sys.modules; "
        "assert 'numpy' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_real_rotated_pdf_renders_pngs():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((20, 40), "Hello", fontsize=20)
    bbox = page.get_texttrace()[0]["bbox"]
    page.set_rotation(90)

    crop = crops.render_review_crop(
        doc, word=(1, bbox), glyph=(1, bbox))

    assert crop.glyph.startswith("data:image/png;base64,")
    assert crop.word.startswith("data:image/png;base64,")
    assert set(crop.overlay) == {"left", "top", "width", "height"}


def test_to_display_bbox_ignores_invalid_input():
    page = FakePage()
    assert crops._display_bbox(page, None) is None
    assert crops._display_bbox(page, (1, 2, 3)) is None
    assert crops._rect((float("nan"), 0, 1, 1)) is None
