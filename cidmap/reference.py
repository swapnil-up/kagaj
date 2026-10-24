"""Optional reference-font inference for unknown CIDs.

The embedded font subsets in a PDF renumber glyph IDs, so an external CID table
is not directly usable. The original font is still useful as a shape oracle:
extract each embedded glyph's outline, compare it with the reference font, and
use the reference font's cmap/GSUB rules to recover the intended Unicode.

This module is a suggestion engine, not a source of truth. Results are meant for
the review sheet; a human still confirms every mapping.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

from .embedded import quiet_fonttools
from .fingerprint import font_signature
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
    exact: bool = False
    references: int = 1


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


class ReferenceEnsemble:
    """Match a shape against every available copy of a reference family.

    Exactness is intentionally strict: a value is exact only when every
    reference returns a zero-distance outline. Single-reference use keeps the
    historical ``ReferenceIndex`` behaviour.
    """

    def __init__(self, indexes):
        self.indexes = tuple(index for index in indexes if index is not None)
        if not self.indexes:
            raise ValueError("reference ensemble needs at least one font")

    @classmethod
    def from_paths(cls, paths) -> "ReferenceEnsemble":
        from .reference_fonts import resolve_reference_fonts

        resolved = []
        seen = set()
        for value in paths:
            for path in resolve_reference_fonts(value):
                key = str(path.resolve())
                if key not in seen:
                    seen.add(key)
                    resolved.append(path)
        return cls(ReferenceIndex.from_path(path) for path in resolved)

    @classmethod
    def from_value(cls, value) -> "ReferenceEnsemble":
        return cls.from_paths([value])

    @property
    def primary(self) -> ReferenceIndex:
        return self.indexes[0]

    @property
    def path(self) -> str:
        return self.primary.path

    def metadata(self) -> dict:
        meta = self.primary.metadata()
        meta["references"] = [index.metadata() for index in self.indexes]
        meta["reference_count"] = len(self.indexes)
        return meta

    def shape_for(self, name: str):
        return self.primary.shape_for(name)

    def values_for(self, name: str):
        return self.primary.values_for(name)

    def suggest(self, shape: GlyphShape | None,
                limit: int = _MAX_CANDIDATES) -> list[ReferenceMatch]:
        if shape is None:
            return []
        total = len(self.indexes)
        evidence: dict[str, dict] = {}
        for position, index in enumerate(self.indexes):
            for match in index.suggest(shape, limit=max(limit * 3, 15)):
                item = evidence.setdefault(match.value, {
                    "scores": {},
                    "glyphs": set(),
                })
                item["scores"][position] = match.score
                item["glyphs"].add(match.glyph)
        scored = []
        for value, item in evidence.items():
            scores = [item["scores"][i] for i in range(total)
                      if i in item["scores"]]
            exact = len(scores) == total and all(
                item["scores"].get(i) == 0.0 for i in range(total))
            score = max(scores)
            scored.append((
                score, value, "/".join(sorted(item["glyphs"])), exact,
                len(scores),
            ))
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        matches = []
        for score, value, glyph, exact, references in scored:
            label = "exact" if exact else f"{glyph} \u00b7 score {score:.1f}"
            if total > 1:
                label += f" \u00b7 {references}/{total} refs"
            matches.append(ReferenceMatch(
                value=value,
                glyph=glyph,
                score=score,
                detail=label,
                exact=exact,
                references=references,
            ))
            if len(matches) >= limit:
                break
        return matches


class ReferenceIndex:
    """Glyph shapes plus Unicode roles from an original font and its GSUB."""

    def __init__(self, font: TTFont, path: str | Path | None = None):
        self.path = str(path) if path else ""
        self.sha256 = _file_sha256(path) if path else ""
        self.signature = font_signature(font, Path(path).name if path else "")
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
        from .reference_fonts import resolve_reference_font

        return _load_reference(str(resolve_reference_font(path).resolve()))

    @classmethod
    def from_font(cls, font: TTFont) -> "ReferenceIndex":
        return cls(font)

    def metadata(self) -> dict:
        """Provenance for diagnostics; log this with every match report."""
        signature = self.signature
        return {
            "path": self.path,
            "sha256": self.sha256,
            "family": signature.family,
            "style": signature.style,
            "version": signature.version.strip(),
            "created": signature.created,
            "family_hash": signature.family_hash,
        }

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
            exact = score == 0.0
            for value in values:
                scored.append((score, value, name, exact))
        scored.sort()
        seen = set()
        matches = []
        for score, value, name, exact in scored:
            if value in seen:
                continue
            seen.add(value)
            matches.append(ReferenceMatch(
                value=value,
                glyph=name,
                score=score,
                detail=(f"exact \u00b7 {name}" if exact
                        else f"{name} \u00b7 score {score:.1f}"),
                exact=exact,
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


def _file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=8)
def _load_reference(path: str) -> ReferenceIndex:
    with quiet_fonttools():
        font = TTFont(path, fontNumber=0, lazy=False)
        return ReferenceIndex(font, path)
