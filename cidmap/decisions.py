"""Validate and apply neutral review decisions to the canonical store.

The review harness exports font-scoped records shaped as
``{key, value, undecodable, inconsistent, note, data}``. Both ``cidmap commit``
and ``cidmap promote --apply`` use this module so the two write paths cannot
diverge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mappings import mark_undecodable, set_value


class DecisionError(ValueError):
    """A review decision cannot be committed without losing information."""


@dataclass
class DecisionResult:
    values: int = 0
    undecodable: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def decision_fields(record: dict) -> tuple[str, int, str, bool, bool, str]:
    """Return ``(font, cid, value, undecodable, inconsistent, note)``."""
    if not isinstance(record, dict) or "key" not in record:
        raise DecisionError(
            "legacy bare-CID corrections are not accepted; run derive and "
            "seed them, or re-review with a font-scoped sheet")
    data = record.get("data") or {}
    font = data.get("font_id") or data.get("font") or ""
    raw_cid = data.get("cid")
    key = str(record["key"])
    if raw_cid is None and "\u2571" in key:
        raw_cid = key.rsplit("\u2571", 1)[-1]
    if raw_cid is None:
        raise DecisionError(f"decision {key!r} has no CID")
    if not font:
        raise DecisionError(
            f"decision {key!r} has no font identity; bare-CID values are "
            "not accepted")
    try:
        cid = int(raw_cid)
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"decision {key!r} has an invalid CID") from exc
    return (font, cid, (record.get("value") or "").strip(),
            bool(record.get("undecodable")),
            bool(record.get("inconsistent")),
            str(record.get("note") or "").strip())


def apply_decisions(store: dict, decisions: list[dict]) -> DecisionResult:
    """Apply neutral decisions in memory; callers save only when ``ok``."""
    result = DecisionResult()
    for i, record in enumerate(decisions, 1):
        try:
            font, cid, value, undecodable, inconsistent, note = (
                decision_fields(record))
        except DecisionError as exc:
            result.errors.append(f"record {i}: {exc}")
            continue
        where = f"record {i} ({font}\u2571{cid})"
        if inconsistent:
            result.errors.append(
                f"{where}: inconsistent samples need engineering follow-up"
                + (f" ({note})" if note else ""))
            continue
        if undecodable and value:
            result.errors.append(f"{where}: cannot be both undecodable and a value")
            continue
        if not undecodable and not value:
            result.errors.append(
                f"{where}: empty value; use undecodable explicitly")
            continue

        undec_key = f"{font}\u2571{cid}"
        marked_undec = undec_key in store.get("undecodable", [])
        existing = store.get("fonts", {}).get(font, {}).get(cid)
        if existing is not None:
            if undecodable or value != existing:
                result.errors.append(
                    f"{where}: conflicts with stored value {existing!r}")
            else:
                result.unchanged += 1
            continue
        if marked_undec and value:
            result.errors.append(f"{where}: already marked undecodable")
            continue
        if undecodable:
            if marked_undec:
                result.unchanged += 1
            else:
                mark_undecodable(store, font, cid)
                result.undecodable += 1
            continue
        metadata = record.get("data") or {}
        source = metadata.get("source") or record.get("source") or "review"
        set_value(store, font, cid, value, {"source": source})
        result.values += 1
    return result
