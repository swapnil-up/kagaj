"""Detect and decode legacy 8-bit Nepali fonts.

A number of commonly used PDF fonts predate Unicode and store Devanagari in
ASCII byte positions.  Many of them share the Preeti keyboard layout closely
enough for the existing deterministic Preeti decoder to produce useful text.
Others use private binary encodings.  Those are decoded from the external
``cidmap/data/legacy_fonts.json`` table when it has been supplied by
``cidmap legacy-import``; otherwise they remain marked as unknown.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from migration_parser.preeti import decode as _decode_preeti

from .legacy_tables import DEFAULT_TABLE, load_table as _load_table

_FAMILIES: tuple[tuple[str, str], ...] = (
    ("genaakriti", "gen-aakriti"),
    ("genganess", "gen-ganess"),
    ("genrukminibold", "gen-rukmini"),
    ("gensumodbold", "gen-sumod"),
    ("genfontasyhimalittnormal", "fontasy"),
    ("genfontasyhimalitt", "fontasy"),
    ("genfontasyhimali", "fontasy"),
    ("genpreeti", "preeti"),
    ("fontasyhimalittnormal", "fontasy"),
    ("fontasyhimalitt", "fontasy"),
    ("fontasyhimali", "fontasy"),
    ("fontasy", "fontasy"),
    ("kantipur", "kantipur"),
    ("himalayabold", "preeti"),
    ("shreenathbold", "preeti"),
    ("cvshrinagar", "preeti"),
    ("himalaya", "preeti"),
    ("himalb", "preeti"),
    ("nagarik", "preeti"),
    ("aakriti", "preeti"),
    ("ganesh", "preeti"),
    ("ganess", "preeti"),
    ("shreenath", "preeti"),
    ("devexcel", "preeti"),
    ("aalekh", "preeti"),
    ("xb54b57d7", "preeti"),
    ("preeti", "preeti"),
)

_SUPPORTED = frozenset({"preeti", "fontasy"})
_TABLE_PATH = DEFAULT_TABLE
_TABLE = _load_table(_TABLE_PATH)
_GEN_ASCII_PATH = Path(__file__).resolve().parent / "data" / "gen_fonts_ascii.json"


def _load_gen_ascii(path: str | Path | None = None) -> dict[str, dict[int, str]]:
    source = Path(path) if path else _GEN_ASCII_PATH
    if not source.exists():
        return {}
    with open(source, encoding="utf-8") as handle:
        payload = json.load(handle)
    out = {}
    for name, entry in payload.get("families", {}).items():
        cids = entry.get("cids", {})
        out[name] = {int(cid): value for cid, value in cids.items()}
    return out


_GEN_ASCII = _load_gen_ascii()


def reload_gen_ascii(path: str | Path | None = None) -> dict[str, dict[int, str]]:
    global _GEN_ASCII
    _GEN_ASCII = _load_gen_ascii(path)
    return _GEN_ASCII


_DIGITS = re.compile(r"(?<![A-Za-z])[0-9]+(?:[.,][0-9]+)*(?![A-Za-z])")
_NUMERIC = re.compile(r"^[\s0-9.,%+\-/*()]+$")
_FONTASY_OVERRIDES = str.maketrans({
    "@": "\u0926\u094d\u0926",
    "%": "\u091b",
    "^": "\u091f",
    "(": "\u0922",
    ")": "\u0923\u094d",
})


def _normalize(base_font: str) -> str:
    name = (base_font or "").split("+")[-1]
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def reload_table(path: str | None = None) -> dict:
    """Reload the external legacy table, primarily for imports and tests."""
    global _TABLE, _TABLE_PATH
    _TABLE_PATH = path or DEFAULT_TABLE
    _TABLE = _load_table(_TABLE_PATH)
    return _TABLE


def _table_family(name: str) -> str | None:
    for canonical, entry in _TABLE.get("families", {}).items():
        for alias in entry.get("base_fonts", ()):
            if name == alias or name.startswith(alias):
                return canonical
    return None


def family(base_font: str) -> str | None:
    """Return the canonical legacy family for a BaseFont name, if any."""
    name = _normalize(base_font)
    if not name:
        return None
    for alias, canonical in _FAMILIES:
        if name == alias or name.startswith(alias):
            return canonical
    return _table_family(name)


def is_legacy(base_font: str) -> bool:
    return family(base_font) is not None


def supported(base_font_or_family: str) -> bool:
    canonical = family(base_font_or_family) or base_font_or_family
    return (canonical in _SUPPORTED or canonical in _GEN_ASCII
            or canonical in _TABLE.get("families", {}))


def _decode_fontasy(text: str) -> str:
    if text.strip() and _NUMERIC.fullmatch(text.strip()):
        return text
    text = text.translate(_FONTASY_OVERRIDES)
    parts = []
    start = 0
    for match in _DIGITS.finditer(text):
        parts.append(_decode_preeti(text[start:match.start()]))
        parts.append(match.group())
        start = match.end()
    parts.append(_decode_preeti(text[start:]))
    return "".join(parts)


_DECODERS = {
    "preeti": _decode_preeti,
    "fontasy": _decode_fontasy,
}


def table_family(family: str) -> bool:
    return (family in _GEN_ASCII
            or (family not in _DECODERS
                and family in _TABLE.get("families", {})))


def decode(text: str, family: str) -> str | None:
    """Decode text in a known legacy family, or return None if unsupported."""
    gen_codes = _GEN_ASCII.get(family)
    if gen_codes is not None:
        return _decode_preeti("".join(
            gen_codes.get(ord(char), char) for char in text))
    decoder = _DECODERS.get(family)
    if decoder is not None:
        return decoder(text)
    entry = _TABLE.get("families", {}).get(family)
    if entry is None:
        return None
    codes = entry.get("codes", {})
    return "".join(codes.get(ord(char), char) for char in text)


def decode_cids(cids, family: str) -> str | None:
    """Decode PDF CIDs for a complete external table family."""
    gen_codes = _GEN_ASCII.get(family)
    if gen_codes is not None:
        try:
            chars = [gen_codes[int(cid)] for cid in cids]
        except KeyError:
            return None
        return _decode_preeti("".join(chars))
    entry = _TABLE.get("families", {}).get(family)
    if entry is None:
        return None
    codes = entry.get("codes", {})
    values = []
    for cid in cids:
        value = codes.get(int(cid))
        if value is None:
            return None
        values.append(value)
    return "".join(values)


def decode_font(text: str, base_font: str) -> str | None:
    """Decode text using the legacy family inferred from a BaseFont name."""
    canonical = family(base_font)
    if canonical is None:
        return None
    return decode(text, canonical)
