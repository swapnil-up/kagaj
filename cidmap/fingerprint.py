"""Stable glyph, subset, and font-build fingerprints for diagnostics."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont

from .shape import glyph_shape

_NAME_IDS = {
    "family": 1,
    "style": 2,
    "full": 4,
    "version": 5,
}


@dataclass(frozen=True)
class GlyphFingerprint:
    outline_hash: str
    shape_hash: str
    advance: float
    bbox: tuple[float, float, float, float]
    contours: int
    points: int

    @property
    def short(self) -> str:
        return self.outline_hash[:12]


@dataclass(frozen=True)
class FontSignature:
    base_font: str
    family: str
    style: str
    full: str
    version: str
    upm: int
    glyph_count: int
    tables: tuple[str, ...]
    gsub_features: tuple[str, ...]
    gsub_lookups: int
    family_hash: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["tables"] = list(self.tables)
        data["gsub_features"] = list(self.gsub_features)
        return data


def _digest(payload) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _outline_points(glyph_set, name, upm):
    recording = RecordingPen()
    glyph_set[name].draw(recording)
    scale = 1000.0 / upm
    parts = []
    for op, points in recording.value:
        normalized = []
        for point in points:
            if point is None or len(point) < 2:
                normalized.append(None)
                continue
            x, y = point[0], point[1]
            if x is None or y is None:
                normalized.append(None)
            else:
                normalized.append((round(x * scale, 3),
                                   round(y * scale, 3)))
        parts.append((op, tuple(normalized)))
    return parts


def glyph_fingerprint(glyph_set, name, hmtx, upm) -> GlyphFingerprint:
    """Fingerprint one glyph independent of its glyph ID or name."""
    shape = glyph_shape(glyph_set, name, hmtx, upm)
    outline = _outline_points(glyph_set, name, upm)
    shape_payload = {
        "bbox": [round(value, 3) for value in shape.value],
        "advance": round(shape.advance, 3),
        "contours": shape.contours,
        "points": shape.points,
        "bitmap": list(shape.bitmap),
    }
    return GlyphFingerprint(
        outline_hash=_digest(outline),
        shape_hash=_digest(shape_payload),
        advance=shape.advance,
        bbox=shape.value,
        contours=shape.contours,
        points=shape.points,
    )


def subset_signature(font: TTFont) -> str:
    """Hash the multiset of glyph fingerprints in an embedded subset."""
    glyph_set = font.getGlyphSet()
    hmtx = font["hmtx"]
    upm = font["head"].unitsPerEm
    hashes = sorted(
        glyph_fingerprint(glyph_set, name, hmtx, upm).outline_hash
        for name in font.getGlyphOrder()
    )
    return _digest(hashes)


def _name(font: TTFont, name_id: int) -> str:
    table = font.get("name")
    if table is None:
        return ""
    try:
        record = table.getName(name_id, 3, 1, 0x409)
        if record is None:
            record = table.getName(name_id, 3, 1)
        if record is None:
            record = table.getName(name_id, 1, 0)
        return str(record.toUnicode()) if record is not None else ""
    except Exception:
        return ""


def _gsub(font: TTFont) -> tuple[tuple[str, ...], int]:
    if "GSUB" not in font:
        return (), 0
    gsub = font["GSUB"].table
    features = ()
    if gsub.FeatureList is not None:
        tags = {record.FeatureTag for record in gsub.FeatureList.FeatureRecord}
        features = tuple(sorted(tags))
    lookups = len(gsub.LookupList.Lookup) if gsub.LookupList is not None else 0
    return features, lookups


def font_signature(font: TTFont, base_font: str = "") -> FontSignature:
    """Best-effort family/build signature; subsets can still differ."""
    upm = font["head"].unitsPerEm
    glyph_count = len(font.getGlyphOrder())
    tables = tuple(sorted(font.keys()))
    gsub_features, gsub_lookups = _gsub(font)
    family = _name(font, _NAME_IDS["family"])
    style = _name(font, _NAME_IDS["style"])
    full = _name(font, _NAME_IDS["full"])
    version = _name(font, _NAME_IDS["version"])
    stable = {
        "base_font": (base_font or "").split("+")[-1],
        "family": family,
        "style": style,
        "full": full,
        "version": version,
        "upm": upm,
        "tables": list(tables),
        "gsub_features": list(gsub_features),
        "gsub_lookups": gsub_lookups,
    }
    return FontSignature(
        base_font=base_font,
        family=family,
        style=style,
        full=full,
        version=version,
        upm=upm,
        glyph_count=glyph_count,
        tables=tables,
        gsub_features=gsub_features,
        gsub_lookups=gsub_lookups,
        family_hash=_digest(stable),
    )
