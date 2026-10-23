"""Resolve PyMuPDF font resources to stable, decoding-safe font identities.

Text spans only carry the BaseFont name (``Kalimati``), not the subset resource
name promised by the older census docs. The same CID can mean different glyphs
in different embedded subsets, so a font identity must be derived from the
PDF's font object, not the span name.

Preferred identity is the ToUnicode CMap bytes: two fonts that map a CID to the
same Unicode are interchangeable for decoding. When a usable CMap is absent we
fall back to a PDF-local source hash plus font xref and mark the scheme.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

_DO_RE = re.compile(r"/([^\s/<>\[\]()]+)\s+Do\b")
_FONT_ENTRY_RE = re.compile(r"/([^\s/<>\[\]()]+)\s+(\d+)\s+\d+\s+R")
_BFCHAR_RE = re.compile(r"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE_RE = re.compile(r"beginbfrange(.*?)endbfrange", re.S)
_HEX_RE = re.compile(r"<([0-9A-Fa-f]+)>")
_RANGE_ITEM_RE = re.compile(
    r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<([0-9A-Fa-f]+)>|\[(.*?)\])",
    re.S)


def _same_base(left: str, right: str) -> bool:
    return left == right or left.split("+")[-1] == right.split("+")[-1]


def lookup_identity(fonts: dict[str, FontIdentity],
                    base: str) -> FontIdentity:
    """Find a page identity for a texttrace BaseFont name."""
    if base in fonts:
        return fonts[base]
    matches = [identity for name, identity in fonts.items()
               if _same_base(name, base)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FontResolutionError(f"font {base!r} not found in page resources")
    raise FontAmbiguity(base, {m.font_xref for m in matches if m.font_xref})


class FontResolutionError(Exception):
    """A page's font resources could not be resolved unambiguously."""


class FontAmbiguity(FontResolutionError):
    """Several font resources on a page share one BaseFont name."""

    def __init__(self, base_font, xrefs):
        self.base_font = base_font
        self.xrefs = sorted(xrefs)
        super().__init__(
            f"ambiguous {base_font!r} on page: xrefs {self.xrefs}")


@dataclass(frozen=True)
class FontIdentity:
    font_id: str
    base_font: str
    font_xref: int | None = None
    font_id_scheme: str = "unresolved"

    @property
    def scheme(self) -> str:
        return self.font_id_scheme


def _clean_name(raw) -> str:
    if raw is None:
        return ""
    return str(raw).strip().lstrip("/").strip("()<>[]")


def _dict_value(doc, xref: int, key: str) -> str | None:
    try:
        kind, value = doc.xref_get_key(xref, key)
    except Exception:
        return None
    if kind == "null" or value is None:
        return None
    return value


def _resolve_dict(doc, raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw.startswith("<<"):
        return raw
    match = re.match(r"\s*(\d+)\s+\d+\s+R\s*$", raw)
    if not match:
        return None
    try:
        return doc.xref_object(int(match.group(1)))
    except Exception:
        return None


def _font_entries(doc, xref: int) -> list[tuple[str, int]]:
    raw = _resolve_dict(doc, _dict_value(doc, xref, "Resources/Font"))
    if raw is None:
        raw = _resolve_dict(doc, _dict_value(doc, xref, "Font"))
    if not raw:
        return []
    return [(name, int(ref)) for name, ref in _FONT_ENTRY_RE.findall(raw)]


def _used_xobjects(doc, xref: int) -> list[str]:
    try:
        data = doc.xref_stream(xref)
    except Exception:
        return []
    if not data:
        return []
    text = data.decode("latin-1", errors="ignore")
    return _DO_RE.findall(text)


def _xobject_xref(doc, resources_xref: int, name: str) -> int | None:
    raw = _resolve_dict(doc, _dict_value(doc, resources_xref, "Resources/XObject"))
    if raw is None:
        raw = _resolve_dict(doc, _dict_value(doc, resources_xref, "XObject"))
    if not raw:
        return None
    for candidate, ref in _FONT_ENTRY_RE.findall(raw):
        if candidate == name:
            return int(ref)
    return None


def _collect_fonts(doc, resources_xref: int, contents: list[int],
                   seen_forms: set[int], out: dict[int, str]) -> None:
    for _name, font_xref in _font_entries(doc, resources_xref):
        if font_xref not in out:
            out[font_xref] = _clean_name(
                _dict_value(doc, font_xref, "BaseFont")) or "unknown"
    for content_xref in contents:
        for name in _used_xobjects(doc, content_xref):
            form = _xobject_xref(doc, resources_xref, name)
            if form is None or form in seen_forms:
                continue
            seen_forms.add(form)
            _collect_fonts(doc, form, [form], seen_forms, out)


def page_fonts(page, wanted: set[str] | None = None) -> dict[str, FontIdentity]:
    """Return ``{base_font: identity}`` for the fonts this page can draw with.

    Raises :class:`FontAmbiguity` if one BaseFont has multiple resources; there
    is no safe way to assign a span to one of them.
    """
    doc = getattr(page, "parent", None)
    page_xref = getattr(page, "xref", None)
    if doc is None or page_xref is None:
        return {}

    contents = []
    try:
        contents = [int(x) for x in (page.get_contents() or [])]
    except Exception:
        pass
    fonts: dict[int, str] = {}
    _collect_fonts(doc, page_xref, contents, {page_xref}, fonts)
    by_base: dict[str, set[int]] = defaultdict(set)
    for xref, base in fonts.items():
        by_base[base].add(xref)

    wanted_bases = None
    if wanted is not None:
        exact = {base for base in by_base if base in wanted}
        wanted_bases = exact or {
            base for base in by_base
            if any(_same_base(base, name) for name in wanted)
        }

    out: dict[str, FontIdentity] = {}
    for base, xrefs in by_base.items():
        if wanted_bases is not None and base not in wanted_bases:
            continue
        if len(xrefs) > 1:
            raise FontAmbiguity(base, xrefs)
        xref = next(iter(xrefs))
        out[base] = _identity(doc, base, xref)
    return out


def _hex_codepoints(hex_string: str) -> tuple[int, ...]:
    width = 4 if len(hex_string) <= 4 else 2
    return tuple(int(hex_string[i:i + width], 16)
                 for i in range(0, len(hex_string), width))


def _cmap_mappings(data: bytes) -> list[tuple[int, tuple[int, ...]]]:
    text = data.decode("latin-1", errors="ignore")
    mappings: list[tuple[int, tuple[int, ...]]] = []
    for block in _BFCHAR_RE.findall(text):
        tokens = _HEX_RE.findall(block)
        for i in range(0, len(tokens) - 1, 2):
            mappings.append((int(tokens[i], 16),
                             _hex_codepoints(tokens[i + 1])))
    for block in _BFRANGE_RE.findall(text):
        for lo, hi, _single, one, array in _RANGE_ITEM_RE.findall(block):
            start = int(lo, 16)
            end = int(hi, 16)
            if one:
                cps = _hex_codepoints(one)
                if not cps:
                    continue
                for offset, src in enumerate(range(start, end + 1)):
                    values = list(cps)
                    values[-1] += offset
                    if values[-1] <= 0x10FFFF:
                        mappings.append((src, tuple(values)))
            else:
                for offset, token in enumerate(_HEX_RE.findall(array or "")):
                    cps = _hex_codepoints(token)
                    if cps:
                        mappings.append((start + offset, cps))
    return mappings


def _raw_cmap(doc, font_xref: int) -> bytes | None:
    try:
        kind, value = doc.xref_get_key(font_xref, "ToUnicode")
    except Exception:
        return None
    if kind != "xref" or not value:
        return None
    match = re.search(r"(\d+)\s+\d+\s+R", value)
    if not match:
        return None
    try:
        data = doc.xref_stream(int(match.group(1)))
    except Exception:
        return None
    return data or None


@lru_cache(maxsize=64)
def _cmap_mapping_cached(data: bytes) -> dict[int, tuple[int, ...]] | None:
    mappings = _cmap_mappings(data)
    return dict(mappings) if mappings else None


def cmap_mapping(doc, font_xref: int) -> dict[int, tuple[int, ...]] | None:
    """Return the font's raw ToUnicode ``{cid: codepoints}`` map, if any."""
    data = _raw_cmap(doc, font_xref)
    if data is None:
        return None
    return _cmap_mapping_cached(data)


def _usable_cmap(doc, font_xref: int) -> bytes | None:
    data = _raw_cmap(doc, font_xref)
    if data is None:
        return None
    mappings = _cmap_mapping_cached(data)
    if not mappings:
        return None
    if all(src == dst[0] and len(dst) == 1
           for src, dst in mappings.items()):
        return None
    return data



@lru_cache(maxsize=None)
def _file_sha256(path: str, mtime_ns: int, size: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hash(doc) -> str:
    """Best-effort SHA-256 of the source PDF for PDF-local font identities."""
    name = getattr(doc, "name", "") or ""
    if name and os.path.exists(name):
        stat = os.stat(name)
        return _file_sha256(os.path.abspath(name), stat.st_mtime_ns,
                            stat.st_size)
    try:
        return hashlib.sha256(doc.tobytes()).hexdigest()
    except Exception:
        return "unknown"


def font_identity(doc, base: str, xref: int) -> FontIdentity:
    """Return the decoding-safe identity for one font object."""
    return _identity(doc, base, xref)


def document_fonts(doc, max_pages=None) -> dict[int, str]:
    """Return ``{font_xref: base_font}`` across pages and nested forms."""
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    found: dict[int, str] = {}
    for page_number in pages:
        try:
            page = doc[page_number]
            page_xref = page.xref
            contents = [int(x) for x in (page.get_contents() or [])]
        except Exception:
            continue
        _collect_fonts(doc, page_xref, contents, {page_xref}, found)
    return found


def _identity(doc, base: str, xref: int) -> FontIdentity:
    cmap = _usable_cmap(doc, xref)
    if cmap is not None:
        digest = hashlib.sha1(cmap).hexdigest()[:10]
        return FontIdentity(f"{base}@cmap:{digest}", base, xref, "cmap-hash")
    digest = source_hash(doc)[:8]
    return FontIdentity(f"{base}@src:{digest}:xref{xref}", base, xref,
                        "pdf-local")
