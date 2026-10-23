"""Canonical CID mapping store: load, validate, merge, save.

Schema (version 1):

.. code-block:: json

    {
      "schema_version": 1,
      "fonts": {"KLMNGO+Kalimati-1": {4: "ि", 16: "र्", ...}, ...},
      "cids": {4: {font: scoped_value, ...}, ...},
      "undecodable": ["Kalimati@cmap:abcd123456╱9", ...],
      "meta": {"updated": "...", "source_pdf": "...", "derive": true,
               "font_labels": {"Kalimati@cmap:abcd123456": "Kalimati p1"}}
    }

Two cross-references are kept in sync:
  - ``fonts[font][cid] -> value`` — the lookup surface decoders use
  - ``cids[cid][font] -> value`` — the per-CID audit / review surface

A CID with no font-specific entry can still carry a fallback in ``cids[cid][""]``;
that legacy path exists only for derive output. Reviewed values are always
font-scoped. ``meta.font_labels`` is reserved for optional human labels.

CIDs a reviewer marked undecodable are listed in ``undecodable`` as
``"{font}╱{cid}"``; ``get_value`` returns None for those before any fallback.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def empty_store() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "fonts": {},
        "cids": {},
        "undecodable": [],
        "meta": {"font_labels": {}},
    }


def _validate(store: dict) -> None:
    if store.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {store.get('schema_version')!r}")
    for font, mp in store.get("fonts", {}).items():
        if not isinstance(mp, dict):
            raise ValueError(f"fonts[{font!r}] is not an object")
    for cid, mp in store.get("cids", {}).items():
        if not isinstance(mp, dict):
            raise ValueError(f"cids[{cid!r}] is not an object")
    labels = store.get("meta", {}).get("font_labels", {})
    if labels is not None and not isinstance(labels, dict):
        raise ValueError("meta.font_labels is not an object")


def _normalize(store: dict) -> None:
    """JSON turns integer keys into strings; coerce cid keys back to ints."""
    for font, mp in store.get("fonts", {}).items():
        store["fonts"][font] = {int(k): v for k, v in mp.items()}
    cids = store.get("cids", {})
    for cid, mp in list(cids.items()):
        cids[int(cid)] = mp
        if not isinstance(cid, int):
            del cids[cid]


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return empty_store()
    with open(p, encoding="utf-8") as f:
        store = json.load(f)
    _validate(store)
    _normalize(store)
    return store


def save(store: dict, path: str | Path) -> None:
    _validate(store)
    p = Path(path)
    os.makedirs(p.parent, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, p)


def _norm_font(font: str) -> str:
    return font or ""


def set_value(store: dict, font: str, cid: int, value: str,
              meta: dict | None = None) -> None:
    """Record one font-scoped mapping, keeping both cross-references in sync."""
    font = _norm_font(font)
    store.setdefault("fonts", {}).setdefault(font, {})[cid] = value
    cid_mp = store.setdefault("cids", {}).setdefault(cid, {})
    cid_mp[font] = value
    if meta:
        cid_mp.setdefault("_meta", {}).update(meta)
    store.setdefault("meta", {})["updated"] = datetime.now(
        timezone.utc).isoformat()


def set_font_label(store: dict, font: str, label: str) -> None:
    """Attach an optional human label to a font identity."""
    font = _norm_font(font)
    if not font:
        raise ValueError("font label requires a non-empty font id")
    store.setdefault("meta", {}).setdefault("font_labels", {})[font] = label


def font_label(store: dict, font: str) -> str | None:
    return store.get("meta", {}).get("font_labels", {}).get(
        _norm_font(font))


def set_fallback(store: dict, cid: int, value: str,
                 meta: dict | None = None) -> None:
    """Record a CID-wide fallback (font key ``""``)."""
    set_value(store, "", cid, value, meta)


def get_value(store: dict, font: str, cid: int) -> str | None:
    """Resolve a glyph: font-scoped first, then CID fallback.

    Returns None for CIDs explicitly marked undecodable.
    """
    font = _norm_font(font)
    if f"{font}╱{cid}" in store.get("undecodable", []):
        return None
    scoped = store.get("fonts", {}).get(font, {}).get(cid)
    if scoped is not None:
        return scoped
    by_cid = store.get("cids", {})
    entry = by_cid.get(cid)
    if entry is None:
        entry = by_cid.get(str(cid), {})
    return entry.get("")


def mark_undecodable(store: dict, font: str, cid: int) -> None:
    """Record that (font, cid) could not be deciphered; no value will resolve."""
    font = _norm_font(font)
    key = f"{font}╱{cid}"
    store.setdefault("undecodable", [])
    if key not in store["undecodable"]:
        store["undecodable"].append(key)
    store.setdefault("meta", {})["updated"] = datetime.now(
        timezone.utc).isoformat()


def merge_derive_results(store: dict, derive_results: dict,
                         source: str = "derive") -> int:
    """Fold a derive output dict (mapping/mode per str-keyed CID) into the store.

    OK mappings become CID fallbacks. Line-level patch count returned.
    """
    n = 0
    for cid, r in derive_results.items():
        mapping = r.get("mapping", "")
        if not mapping or r.get("mode") not in ("ok", "partial"):
            continue
        set_fallback(store, int(cid), mapping, {
            "source": source,
            "evidence": r.get("evidence", [])[:2],
        })
        n += 1
    return n