"""Cross-document glyph evidence registry.

The canonical mapping store is font-scoped and keyed by ``(font_id, cid)``.
Embedded subsets renumber glyphs, so those keys cannot travel between PDFs.
This registry instead keys evidence by ``(family_hash, outline_hash)``: the font
build and the normalized outline of the glyph itself.

The registry is evidence only. The decoder continues to read
``cid_mappings.json``; promotion decides when evidence is strong enough to add
a mapping to that store.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .decode import glyphs as extract_glyphs
from .embedded import EmbeddedFontCache
from .fingerprint import font_signature, glyph_fingerprint
from .fonts import FontResolutionError, source_hash

SCHEMA_VERSION = 1
CONFIRMED_SUPPORT = 2
DEFAULT_REGISTRY = Path(__file__).with_name("data") / "glyph_registry.json"


def empty_registry() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "glyphs": {},
        "meta": {},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def glyph_key(family_hash: str, outline_hash: str) -> str:
    return f"{family_hash}:{outline_hash}"


def _validate(registry: dict) -> None:
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported registry schema_version "
            f"{registry.get('schema_version')!r}")
    glyphs = registry.get("glyphs", {})
    if not isinstance(glyphs, dict):
        raise ValueError("registry glyphs is not an object")


def _normalize(registry: dict) -> None:
    for entry in registry.get("glyphs", {}).values():
        entry["documents"] = sorted(set(entry.get("documents") or []))
        entry["values"] = sorted(set(entry.get("values") or []))
        entry["observations"] = sorted(
            entry.get("observations") or [],
            key=lambda obs: (
                obs.get("doc_sha256", ""),
                obs.get("font_id", ""),
                int(obs.get("cid") or 0),
                obs.get("value", ""),
            ),
        )
        entry["conflicts"] = sorted(
            entry.get("conflicts") or [],
            key=lambda conflict: conflict.get("value", ""),
        )
        entry["support"] = len(entry["documents"])


def load(path: str | Path | None = None) -> dict:
    p = Path(path) if path is not None else DEFAULT_REGISTRY
    if not p.exists():
        return empty_registry()
    with open(p, encoding="utf-8") as f:
        registry = json.load(f)
    _validate(registry)
    _normalize(registry)
    return registry


def save(registry: dict, path: str | Path | None = None) -> None:
    _validate(registry)
    _normalize(registry)
    p = Path(path) if path is not None else DEFAULT_REGISTRY
    os.makedirs(p.parent, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def _recompute(entry: dict, *, confirmed_support: int) -> None:
    observations = entry.setdefault("observations", [])
    values = sorted({obs["value"] for obs in observations})
    documents = sorted({obs["doc_sha256"] for obs in observations})
    entry["values"] = values
    entry["documents"] = documents
    entry["support"] = len(documents)
    if values:
        entry["value"] = values[0]
    else:
        entry["value"] = ""

    if len(values) > 1:
        entry["status"] = "conflict"
        entry["value"] = ""
    elif any(obs.get("source") == "review" for obs in observations):
        entry["status"] = "confirmed"
    elif len(documents) >= confirmed_support:
        entry["status"] = "confirmed"
    else:
        entry["status"] = "provisional"

    conflicts = []
    for value in values:
        docs = sorted({
            obs["doc_sha256"] for obs in observations
            if obs["value"] == value
        })
        conflicts.append({"value": value, "documents": docs})
    entry["conflicts"] = conflicts if len(values) > 1 else []


def observe(registry: dict, observation: dict,
            *, confirmed_support: int = CONFIRMED_SUPPORT) -> bool:
    """Add one observation; return True when it was new.

    ``observation`` carries ``family_hash``, ``outline_hash``, ``value``,
    ``font_id``, ``cid``, ``doc_sha256``, optional ``base_font``, ``source``,
    ``evidence``, and ``observed_at``.
    """
    family_hash = str(observation.get("family_hash") or "")
    outline_hash = str(observation.get("outline_hash") or "")
    value = str(observation.get("value") or "")
    if not family_hash or not outline_hash:
        raise ValueError("registry observation needs family and outline hashes")
    if not value:
        raise ValueError("registry observation needs a value")

    key = glyph_key(family_hash, outline_hash)
    entry = registry.setdefault("glyphs", {}).get(key)
    if entry is None:
        entry = registry["glyphs"][key] = {
            "family_hash": family_hash,
            "outline_hash": outline_hash,
            "base_font": str(observation.get("base_font") or ""),
            "value": value,
            "values": [value],
            "status": "provisional",
            "support": 0,
            "documents": [],
            "observations": [],
            "conflicts": [],
        }

    obs = {
        "doc_sha256": str(observation.get("doc_sha256") or ""),
        "font_id": str(observation.get("font_id") or ""),
        "cid": int(observation.get("cid") or 0),
        "value": value,
        "source": str(observation.get("source") or "store"),
        "base_font": str(observation.get("base_font") or ""),
        "evidence": list(observation.get("evidence") or []),
        "observed_at": str(observation.get("observed_at") or _now()),
    }
    identity = (obs["doc_sha256"], obs["font_id"], obs["cid"], obs["value"])
    existing = {
        (item.get("doc_sha256"), item.get("font_id"), item.get("cid"),
         item.get("value"))
        for item in entry["observations"]
    }
    added = identity not in existing
    if added:
        entry["observations"].append(obs)
        if not entry.get("base_font"):
            entry["base_font"] = obs["base_font"]
    _recompute(entry, confirmed_support=confirmed_support)
    registry.setdefault("meta", {})["updated"] = _now()
    return added


def lookup(registry: dict, family_hash: str, outline_hash: str) -> dict | None:
    return registry.get("glyphs", {}).get(glyph_key(family_hash, outline_hash))


def glyph_identity(embedded, xref, cid: int, base_font: str = ""):
    """Return ``(family_hash, outline_hash, fingerprint)`` for one embedded CID."""
    font = embedded.get(xref)
    if font is None or cid < 0 or cid >= len(font.order):
        return None
    signature = font_signature(font.font, base_font)
    fingerprint = glyph_fingerprint(
        font.glyph_set, font.order[cid], font.hmtx, font.upm)
    return signature.family_hash, fingerprint.outline_hash, fingerprint


def resolve_glyph(registry: dict, embedded, xref, cid: int,
                  base_font: str = "") -> dict | None:
    """Resolve an embedded CID through its glyph identity."""
    identity = glyph_identity(embedded, xref, cid, base_font)
    if identity is None:
        return None
    family_hash, outline_hash, fingerprint = identity
    entry = lookup(registry, family_hash, outline_hash)
    if entry is None:
        return None
    return {
        "entry": entry,
        "family_hash": family_hash,
        "outline_hash": outline_hash,
        "fingerprint": fingerprint,
    }


def _doc_identities(doc, max_pages=None, issues=None):
    seen: dict[str, dict] = {}
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    for pn in pages:
        try:
            page_glyphs = extract_glyphs(doc[pn], dedup=True)
        except FontResolutionError as exc:
            if issues is not None:
                issues.append({
                    "page": pn + 1,
                    "kind": type(exc).__name__,
                    "message": str(exc),
                })
            continue
        for glyph in page_glyphs:
            font_id = glyph.get("font_id") or ""
            if not font_id or font_id in seen:
                continue
            seen[font_id] = {
                "base_font": glyph.get("base_font") or font_id,
                "font_xref": glyph.get("font_xref"),
                "font_id_scheme": glyph.get("font_id_scheme") or "unresolved",
            }
    return seen


def ingest_document(doc, store: dict, *, registry: dict | None = None,
                    max_pages=None, source: str | None = None,
                    issues=None) -> int:
    """Record store mappings from one PDF; return the number of new observations."""
    registry = registry if registry is not None else empty_registry()
    embedded = EmbeddedFontCache(doc)
    identities = _doc_identities(doc, max_pages=max_pages, issues=issues)
    doc_sha256 = source_hash(doc)
    added = 0
    cids_meta = store.get("cids", {})
    for font_id, cid_values in sorted(store.get("fonts", {}).items()):
        if not font_id or font_id not in identities:
            continue
        identity = identities[font_id]
        xref = identity.get("font_xref")
        if not xref:
            continue
        for raw_cid, value in sorted(cid_values.items(), key=lambda item: int(item[0])):
            if not value:
                continue
            cid = int(raw_cid)
            glyph_id = glyph_identity(
                embedded, xref, cid, identity.get("base_font") or font_id)
            if glyph_id is None:
                continue
            family_hash, outline_hash, _fingerprint = glyph_id
            meta = {}
            by_cid = cids_meta.get(cid) or cids_meta.get(str(cid)) or {}
            if isinstance(by_cid, dict):
                meta = by_cid.get("_meta") or {}
            if observe(registry, {
                "family_hash": family_hash,
                "outline_hash": outline_hash,
                "value": value,
                "font_id": font_id,
                "cid": cid,
                "doc_sha256": doc_sha256,
                "base_font": identity.get("base_font") or font_id,
                "source": source or meta.get("source") or "store",
                "evidence": (meta.get("evidence") or [])[:2],
            }):
                added += 1
    return added


def format_entry(entry: dict | None) -> str:
    if not entry:
        return "No registry entry."
    lines = [
        f"glyph {entry['family_hash'][:12]}:{entry['outline_hash'][:12]}",
        f"value={entry.get('value') or '(conflict)'} "
        f"status={entry.get('status')} support={entry.get('support')}",
    ]
    documents = entry.get("documents") or []
    if documents:
        lines.append("documents: " + ", ".join(doc[:12] for doc in documents))
    values = entry.get("values") or []
    if len(values) > 1:
        lines.append("values: " + ", ".join(repr(value) for value in values))
    for obs in entry.get("observations") or []:
        lines.append(
            f"  {obs.get('font_id')} cid={obs.get('cid')} "
            f"value={obs.get('value')!r} source={obs.get('source')} "
            f"doc={(obs.get('doc_sha256') or '')[:12]}")
    return "\n".join(lines)
