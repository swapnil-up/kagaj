"""Resolve local reference-font aliases without committing font binaries.

Proprietary fonts (Kokila, Mangal, Nirmala UI) and many legacy 8-bit Nepali
fonts cannot be redistributed. Keep them in ``reference-fonts/`` locally and
refer to them by family alias. The directory is gitignored.

Resolution order: an existing path, then ``$CIDMAP_REFERENCE_FONTS`` (one or
more directories, ``os.pathsep``-separated), then ``reference-fonts/`` at the
repo root. Files are matched by normalized stem, so ``Kokila.ttf`` and
``Kokila Bold.ttf`` both resolve for the ``kokila`` alias.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

_ENV = "CIDMAP_REFERENCE_FONTS"
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DIR = _ROOT / "reference-fonts"

_ALIASES = {
    "kalimati": ("kalimati",),
    "kokila": ("kokila",),
    "mangal": ("mangal",),
    "nirmala": ("nirmala", "nirmalaui"),
    "fontasyhimali": ("fontasy himali", "fontasyhimali", "himali"),
    "himalb": ("himalb",),
    "himalli": ("himalli", "himali"),
    "preeti": ("preeti",),
    "kantipur": ("kantipur",),
    "sagarmatha": ("sagarmatha",),
    "notosansdevanagari": ("noto sans devanagari", "notosansdevanagari"),
    "notoserifdevanagari": ("noto serif devanagari", "notoserifdevanagari"),
    "lohitdevanagari": ("lohit devanagari", "lohitdevanagari"),
    "mukta": ("mukta",),
    "annapurnasil": ("annapurna sil", "annapurnasil"),
    "gargi": ("gargi",),
    "sahadeva": ("sahadeva",),
    "samyak": ("samyak", "samyak devanagari"),
    "madan": ("madan",),
    "samanata": ("samanata",),
}


class ReferenceFontError(ValueError):
    """Raised when a local reference font cannot be resolved."""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def reference_dirs() -> list[Path]:
    dirs = []
    for raw in (os.environ.get(_ENV) or "").split(os.pathsep):
        if raw.strip():
            dirs.append(Path(raw).expanduser())
    dirs.append(_DEFAULT_DIR)
    out = []
    seen = set()
    for path in dirs:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _files(directory: Path):
    if not directory.is_dir():
        return []
    try:
        return [p for p in directory.rglob("*") if p.is_file()]
    except OSError:
        return []


def resolve_reference_fonts(value: str | Path) -> list[Path]:
    """Return every local font matching a path or family alias."""
    raw = str(value).strip()
    if not raw:
        raise ReferenceFontError("reference font is empty")
    direct = Path(raw).expanduser()
    if direct.is_file():
        return [direct]
    if direct.suffix.lower() in {".ttf", ".otf", ".ttc"} or "/" in raw:
        raise ReferenceFontError(f"reference font not found: {raw}")

    alias = _norm(raw)
    stems = _ALIASES.get(alias)
    if stems is None:
        raise ReferenceFontError(
            f"unknown reference-font alias {raw!r}; pass a file path or one of: "
            + ", ".join(sorted(_ALIASES)))
    wanted = {_norm(stem) for stem in stems}
    matches = []
    for directory in reference_dirs():
        for path in _files(directory):
            stem = _norm(path.stem)
            if any(stem == item or stem.startswith(item) for item in wanted):
                matches.append(path)
    if matches:
        return sorted(
            set(matches),
            key=lambda path: (
                any(word in _norm(path.stem)
                    for word in ("bold", "italic", "oblique", "light",
                                 "medium", "black", "thin")),
                _norm(path.stem),
            ),
        )
    searched = ", ".join(str(path) for path in reference_dirs())
    raise ReferenceFontError(
        f"reference font {raw!r} not found; put it in {searched} "
        f"or set {_ENV}")


def resolve_reference_font(value: str | Path) -> Path:
    """Return the first local font for a path or a known family alias."""
    return resolve_reference_fonts(value)[0]


def reference_font_arg(value):
    if value is None:
        return None
    try:
        return str(resolve_reference_font(value))
    except ReferenceFontError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
