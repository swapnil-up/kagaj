"""HarfBuzz shaping for reference and candidate Devanagari runs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from .reference import GlyphShape, ReferenceIndex, quiet_fonttools


@dataclass(frozen=True)
class ShapedGlyph:
    name: str
    glyph_id: int
    cluster: int
    values: tuple[str, ...]
    shape: GlyphShape | None
    x_advance: int
    x_offset: int
    y_offset: int


class ReferenceShaper:
    """Shape text with the original font and keep CIDMap's glyph roles."""

    def __init__(self, path: str | Path, index: ReferenceIndex | None = None):
        try:
            import uharfbuzz
        except ImportError as exc:
            raise RuntimeError(
                "shape-run inference requires uharfbuzz; install "
                "'uharfbuzz>=0.39' or the 'redbook' extra"
            ) from exc
        self.path = Path(path).resolve()
        self._hb = uharfbuzz
        self._blob = uharfbuzz.Blob.from_file_path(str(self.path))
        self._face = uharfbuzz.Face(self._blob)
        self._font = uharfbuzz.Font(self._face)
        with quiet_fonttools():
            self.ttfont = TTFont(str(self.path), fontNumber=0, lazy=False)
        self.index = index or ReferenceIndex.from_font(self.ttfont)
        self._cache: dict[str, tuple[ShapedGlyph, ...]] = {}

    @classmethod
    def from_path(cls, path: str | Path) -> "ReferenceShaper":
        return _load_shaper(str(Path(path).resolve()))

    def shape(self, text: str) -> list[ShapedGlyph]:
        buffer = self._hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        self._hb.shape(self._font, buffer)
        out = []
        for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
            name = self._font.glyph_to_string(info.codepoint)
            out.append(ShapedGlyph(
                name=name,
                glyph_id=info.codepoint,
                cluster=info.cluster,
                values=self.index.values_for(name),
                shape=self.index.shape_for(name),
                x_advance=position.x_advance,
                x_offset=position.x_offset,
                y_offset=position.y_offset,
            ))
        return out

    def shape_cached(self, text: str) -> tuple[ShapedGlyph, ...]:
        if text not in self._cache:
            self._cache[text] = tuple(self.shape(text))
        return self._cache[text]

    def cluster_span(self, text: str, cluster: int) -> str:
        clusters = sorted({glyph.cluster for glyph in self.shape_cached(text)})
        end = len(text)
        for value in clusters:
            if value > cluster:
                end = value
                break
        return text[cluster:end]

    def value_for(self, text: str, glyph: ShapedGlyph) -> str | None:
        span = self.cluster_span(text, glyph.cluster)
        matches = [value for value in glyph.values if value and value in span]
        if not matches:
            return None
        return max(matches, key=len)


@lru_cache(maxsize=4)
def _load_shaper(path: str) -> ReferenceShaper:
    return ReferenceShaper(path)
