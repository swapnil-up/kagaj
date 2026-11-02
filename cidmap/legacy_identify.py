"""Identify legacy 8-bit fonts without guessing their byte mapping.

Identification is intentionally separate from decoding. A font can be
recognised from its PDF name, its embedded name table, a committed/external
table, or an outline match against a local legacy reference font. Fonts that
remain unknown but look like simple ASCII-mapped 8-bit fonts are flagged for
``cidmap legacy-import`` rather than decoded heuristically.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

from . import legacy
from .fingerprint import font_signature, glyph_fingerprint
from .reference_fonts import reference_dirs

_ASCII = range(0x20, 0x7F)


@dataclass(frozen=True)
class LegacyIdentity:
    family: str | None
    supported: bool
    source: str
    confidence: str
    encoding: str
    needs_table: bool
    base_font: str
    font_family: str = ""
    font_full: str = ""
    evidence: str = ""
    reference: str | None = None
    matches: int = 0
    total: int = 0
    legacy_like: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OutlineMatch:
    family: str
    reference: str
    matches: int
    total: int
    ratio: float
    confidence: str


def _signature(font: TTFont | None, base_font: str):
    if font is None:
        return None
    try:
        return font_signature(font, base_font)
    except Exception:
        return None


def _ascii_outlines(font: TTFont) -> dict[int, str]:
    try:
        cmap = font.getBestCmap() or {}
        glyph_set = font.getGlyphSet()
        hmtx = font["hmtx"]
        upm = font["head"].unitsPerEm
    except Exception:
        return {}
    out = {}
    for code in _ASCII:
        name = cmap.get(code)
        if not name:
            continue
        try:
            fingerprint = glyph_fingerprint(glyph_set, name, hmtx, upm)
        except Exception:
            continue
        out[code] = fingerprint.outline_hash
    return out


class LegacyReferenceIndex:
    """Outline fingerprints for local legacy fonts, keyed by ASCII code."""

    def __init__(self, paths=None, *, min_matches: int = 12,
                 min_ratio: float = 0.6):
        self.min_matches = min_matches
        self.min_ratio = min_ratio
        self._entries = []
        self._seen = set()
        for path in self._paths(paths):
            self._add(path)

    @staticmethod
    def _paths(paths):
        if paths is not None:
            return [Path(path) for path in paths]
        out = []
        for directory in reference_dirs():
            if not directory.is_dir():
                continue
            try:
                out.extend(sorted(
                    path for path in directory.rglob("*") if path.is_file()))
            except OSError:
                continue
        return out

    def _add(self, path: Path) -> None:
        family = legacy.family(path.stem)
        if family is None:
            return
        try:
            key = (path.resolve(), path.stat().st_mtime_ns, path.stat().st_size)
        except OSError:
            return
        if key in self._seen:
            return
        self._seen.add(key)
        try:
            font = TTFont(str(path), lazy=False)
            outlines = _ascii_outlines(font)
        except Exception:
            return
        if outlines:
            self._entries.append((family, str(path), outlines))

    @classmethod
    def from_local(cls) -> "LegacyReferenceIndex":
        return cls()

    def match(self, font: TTFont) -> OutlineMatch | None:
        embedded = _ascii_outlines(font)
        if len(embedded) < self.min_matches:
            return None
        best = None
        for family, path, reference in self._entries:
            common = embedded.keys() & reference.keys()
            if len(common) < self.min_matches:
                continue
            matches = sum(
                embedded[code] == reference[code] for code in common)
            total = len(common)
            ratio = matches / total
            candidate = OutlineMatch(
                family, path, matches, total, ratio,
                "high" if matches >= 30 and ratio >= 0.95 else "medium")
            if best is None or (
                    candidate.matches, candidate.ratio) > (
                    best.matches, best.ratio):
                best = candidate
        if best is None:
            return None
        if best.matches < self.min_matches or best.ratio < self.min_ratio:
            return None
        return best


def _encoding(family: str) -> str:
    return legacy.encoding(family)


def _identity(family: str, source: str, confidence: str, base_font: str,
              signature=None, *, evidence: str = "",
              reference: str | None = None, matches: int = 0,
              total: int = 0) -> LegacyIdentity:
    supported = legacy.supported(family)
    return LegacyIdentity(
        family=family,
        supported=supported,
        source=source,
        confidence=confidence,
        encoding=_encoding(family),
        needs_table=not supported,
        base_font=base_font,
        font_family=getattr(signature, "family", "") or "",
        font_full=getattr(signature, "full", "") or "",
        evidence=evidence,
        reference=reference,
        matches=matches,
        total=total,
    )


def _name_source(name: str, base_font: str) -> str:
    source = legacy.family_source(name)
    if source in {"gen-ascii", "external-table"}:
        return "table"
    return "base-font" if name == base_font else "font-name"


def _legacy_like(font: TTFont | None, simple: bool | None) -> tuple[bool, str]:
    if simple is False or font is None:
        return False, ""
    try:
        cmap = font.getBestCmap() or {}
        glyph_count = len(font.getGlyphOrder())
    except Exception:
        return False, ""
    if not cmap or any(code > 0x7F for code in cmap):
        return False, ""
    if not any(code in cmap for code in _ASCII):
        return False, ""
    if glyph_count > 256:
        return False, ""
    evidence = (
        f"simple={str(simple).lower() if simple is not None else 'unknown'} "
        f"ascii_cmap={len(cmap)} glyphs={glyph_count}")
    return True, evidence


def identify_font(base_font: str, font: TTFont | None = None, *,
                  simple: bool | None = None,
                  references: LegacyReferenceIndex | None = None
                  ) -> LegacyIdentity:
    """Return the best available identity for a font, without decoding it."""
    base = base_font or ""
    signature = _signature(font, base)
    names = [base]
    if signature is not None:
        for value in (signature.base_font, signature.family,
                      signature.full, signature.style):
            if value and value not in names:
                names.append(value)

    for name in names:
        family = legacy.family(name)
        if family is None:
            continue
        source = _name_source(name, base)
        evidence = f"matched {name!r}"
        if name != base:
            evidence = f"embedded name {name!r}"
        return _identity(family, source, "high", base, signature,
                         evidence=evidence)

    if references is not None and font is not None and simple is not False:
        match = references.match(font)
        if match is not None:
            evidence = (
                f"outline match {match.matches}/{match.total} "
                f"against {match.reference}")
            return _identity(
                match.family, "reference-outline", match.confidence, base,
                signature, evidence=evidence, reference=match.reference,
                matches=match.matches, total=match.total)

    legacy_like, evidence = _legacy_like(font, simple)
    if legacy_like:
        return LegacyIdentity(
            family=None,
            supported=False,
            source="ascii-structure",
            confidence="low",
            encoding="8-bit",
            needs_table=True,
            base_font=base,
            font_family=getattr(signature, "family", "") or "",
            font_full=getattr(signature, "full", "") or "",
            evidence=evidence,
            legacy_like=True,
        )

    encoding = "unicode" if simple is False else "unknown"
    return LegacyIdentity(
        family=None,
        supported=False,
        source="unknown",
        confidence="low",
        encoding=encoding,
        needs_table=False,
        base_font=base,
        font_family=getattr(signature, "family", "") or "",
        font_full=getattr(signature, "full", "") or "",
    )
