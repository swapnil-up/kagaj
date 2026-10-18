"""Validation and review flags for extracted zones.

Runs invariants over the deterministically-parsed fields and annotates each zone
with ``review_flags``. Nothing here silently drops data — suspicious rows are
kept and flagged so a human (or the `validate` command) can inspect the source
snippet/coordinates that produced them.
"""

from __future__ import annotations

MIN_AREAS = 1


def flag_zone(zone: dict, columns: set[str] | None = None) -> list[str]:
    def want(*names: str) -> bool:
        return columns is None or any(n in columns for n in names)

    flags = list(zone.get("time_tags") or [])
    if want("days") and not zone.get("days"):
        flags.append("days_missing")
    if want("dma") and not zone.get("dma"):
        flags.append("dma_missing")
    if want("areas") and len(zone.get("areas_np") or []) < MIN_AREAS and len(zone.get("areas_en") or []) < MIN_AREAS:
        flags.append("areas_missing")
    if want("time", "time_from", "time_to") and zone.get("crosses_midnight") is None and not zone.get("time_from"):
        flags.append("time_missing")
    return sorted(set(flags))


def validate_zone(zone: dict) -> dict:
    zone = dict(zone)
    cols = set(zone.get("source_columns") or [])
    zone["review_flags"] = flag_zone(zone, cols or None)
    return zone


def summarize(zones: list[dict]) -> dict:
    counts: dict[str, int] = {}
    flagged = 0
    for z in zones:
        fl = z.get("review_flags") or []
        if fl:
            flagged += 1
        for f in fl:
            counts[f] = counts.get(f, 0) + 1
    return {"total": len(zones), "flagged": flagged, "by_flag": counts}


def flagged_zones(zones: list[dict]) -> list[dict]:
    return [z for z in zones if z.get("review_flags")]
