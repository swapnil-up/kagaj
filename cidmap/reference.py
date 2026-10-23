"""Optional reference-font inference for unknown CIDs.

The embedded font subsets in a PDF renumber glyph IDs, so an external CID table
is not directly usable. The original font is still useful as a shape oracle:
extract each embedded glyph's outline, compare it with the reference font, and
use the reference font's cmap/GSUB rules to recover the intended Unicode.

This module is a suggestion engine, not a source of truth. Results are meant for
the review sheet; a human still confirms every mapping.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from .embedded import quiet_fonttools
from .shape import GlyphShape, glyph_shape as _shape

_UNI_NAME = re.compile(r"^(?:uni|u)([0-9A-Fa-f]{4,6})(?:\.|$)")
_MAX_CANDIDATES = 5
_BBOX_TOLERANCE = 4.0
_ADVANCE_TOLERANCE = 4.0


@dataclass(frozen=True)
class ReferenceMatch:
    value: str
    glyph: str
    score: float
    detail: str


def _subtables(lookup):
    for subtable in lookup.SubTable:
        nested = getattr(subtable, "ExtSubTable", None)
        yield nested if nested is not None else subtable


def _concat(left: set[str], right: set[str]) -> set[str]:
    if not left or not right:
        return set()
    return {a + b for a in left for b in right}


def _reference_roles(font: TTFont) -> dict[str, set[str]]:
    roles: dict[str, set[str]] = defaultdict(set)
    for codepoint, name in (font.getBestCmap() or {}).items():
        if codepoint >= 0x20:
            roles[name].add(chr(codepoint))
    for name in font.getGlyphOrder():
        match = _UNI_NAME.match(name)
        if match:
            codepoint = int(match.group(1), 16)
            if codepoint >= 0x20:
                roles[name].add(chr(codepoint))
    if "GSUB" not in font:
        return roles

    gsub = font["GSUB"].table
    if gsub.LookupList is None:
        return roles
    for _ in range(12):
        before = {name: set(values) for name, values in roles.items()}
        for lookup in gsub.LookupList.Lookup:
            for subtable in _subtables(lookup):
                mapping = getattr(subtable, "mapping", None)
                if mapping:
                    for source, target in mapping.items():
                        if isinstance(target, (list, tuple)):
                            values = {""}
                            for component in target:
                                values = _concat(
                                    values, roles.get(component, set()))
                                if not values:
                                    break
                            roles[source].update(values)
                            continue
                        if roles.get(source):
                            roles[target].update(roles[source])
                        if roles.get(target):
                            roles[source].update(roles[target])

                alternates = getattr(subtable, "alternates", None)
                if alternates:
                    for source, targets in alternates.items():
                        for target in targets:
                            if roles.get(source):
                                roles[target].update(roles[source])
                            if roles.get(target):
                                roles[source].update(roles[target])

                ligatures = getattr(subtable, "ligatures", None)
                if ligatures:
                    for first, entries in ligatures.items():
                        for entry in entries:
                            components = [first, *entry.Component]
                            values = {""}
                            for component in components:
                                values = _concat(values, roles.get(component, set()))
                                if not values:
                                    break
                            roles[entry.LigGlyph].update(values)
        if roles == before:
            break
    return roles


class ReferenceIndex:
    """Glyph shapes plus Unicode roles from an original font and its GSUB."""

    def __init__(self, font: TTFont):
        self.glyph_set = font.getGlyphSet()
        self.order = font.getGlyphOrder()
        self.hmtx = font["hmtx"]
        self.upm = font["head"].unitsPerEm
        roles = _reference_roles(font)
        self._shapes: list[tuple[GlyphShape, str, tuple[str, ...]]] = []
        self._by_name: dict[str, tuple[GlyphShape, tuple[str, ...]]] = {}
        for name in self.order:
            values = tuple(sorted(roles.get(name, ())))
            if not values:
                continue
            shape = _shape(self.glyph_set, name, self.hmtx, self.upm)
            self._shapes.append((shape, name, values))
            self._by_name[name] = (shape, values)

    @classmethod
    def from_path(cls, path: str | Path) -> "ReferenceIndex":
        return _load_reference(str(Path(path).resolve()))

    @classmethod
    def from_font(cls, font: TTFont) -> "ReferenceIndex":
        return cls(font)

    def shape_for(self, name: str) -> GlyphShape | None:
        entry = self._by_name.get(name)
        return entry[0] if entry else None

    def values_for(self, name: str) -> tuple[str, ...]:
        entry = self._by_name.get(name)
        return entry[1] if entry else ()

    def suggest(self, shape: GlyphShape | None,
                limit: int = _MAX_CANDIDATES) -> list[ReferenceMatch]:
        if shape is None:
            return []
        scored = []
        for reference, name, values in self._shapes:
            score = shape_distance(shape, reference)
            if score >= _NO_MATCH_SCORE:
                continue
            for value in values:
                scored.append((score, value, name))
        scored.sort()
        seen = set()
        matches = []
        for score, value, name in scored:
            if value in seen:
                continue
            seen.add(value)
            matches.append(ReferenceMatch(
                value=value,
                glyph=name,
                score=score,
                detail=f"{name} \u00b7 score {score:.1f}",
            ))
            if len(matches) >= limit:
                break
        return matches


_NO_MATCH_SCORE = 1e6


def shape_distance(left: GlyphShape | None,
                   right: GlyphShape | None) -> float:
    """Return a lower-is-better outline distance; unmatched shapes are huge."""
    if left is None or right is None:
        return _NO_MATCH_SCORE
    bbox = sum(abs(a - b) for a, b in zip(left.value, right.value))
    advance = abs(left.advance - right.advance)
    if bbox > _BBOX_TOLERANCE or advance > _ADVANCE_TOLERANCE:
        return _NO_MATCH_SCORE
    contour_penalty = 2.0 * abs(left.contours - right.contours)
    bitmap = len(set(left.bitmap) ^ set(right.bitmap))
    return bbox + advance + contour_penalty + bitmap * 0.25


@lru_cache(maxsize=8)
def _load_reference(path: str) -> ReferenceIndex:
    with quiet_fonttools():
        font = TTFont(path, fontNumber=0, lazy=False)
        return ReferenceIndex(font)
