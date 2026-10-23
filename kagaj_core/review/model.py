"""Neutral review records shared by every unknown-glyph review sheet.

Adapters build :class:`ReviewItem` values from their own domain data, hand
already-rendered image ``src`` strings to :class:`ReviewCrop`, and convert the
exported :class:`ReviewDecision` records back into their command formats.

Nothing here knows about PDFs, fonts, CIDs, or any parser package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class ReviewCandidate:
    """One suggested value for a review item."""

    value: str
    label: str = ""
    count: int = 0
    detail: str = ""


@dataclass(frozen=True)
class ReviewCrop:
    """Rendered evidence for an item.

    ``glyph`` and ``word`` are any strings usable as an ``<img src>``: a data
    URI, an asset path, or a URL. ``overlay`` holds percentage strings for the
    highlighted glyph region inside the word crop.
    """

    glyph: str | None = None
    word: str | None = None
    overlay: Mapping[str, str] | None = None
    caption: str = ""


@dataclass(frozen=True)
class ReviewItem:
    """A single decision the human must make."""

    key: str
    label: str
    group: str = ""
    context: str = ""
    current: str | None = None
    candidates: tuple[ReviewCandidate, ...] = ()
    crops: tuple[ReviewCrop, ...] = ()
    data: Mapping[str, object] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)
    input_placeholder: str = ""


@dataclass(frozen=True)
class ReviewDecision:
    """A neutral decision record, the shape the renderer exports."""

    key: str
    value: str = ""
    undecodable: bool = False
    inconsistent: bool = False
    note: str = ""
    data: Mapping[str, object] = field(default_factory=dict)

    def to_record(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "undecodable": bool(self.undecodable),
            "inconsistent": bool(self.inconsistent),
            "note": self.note,
            "data": dict(self.data),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> "ReviewDecision":
        return cls(
            key=str(record["key"]),
            value=str(record.get("value") or ""),
            undecodable=bool(record.get("undecodable")),
            inconsistent=bool(record.get("inconsistent")),
            note=str(record.get("note") or ""),
            data=dict(record.get("data") or {}),
        )


def parse_decisions(records, *, convert=None) -> list[ReviewDecision]:
    """Parse neutral decision records.

    ``convert`` optionally maps a legacy adapter record to a neutral one; it
    returns ``None`` to drop the record.
    """

    out: list[ReviewDecision] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if "key" not in record:
            if convert is None:
                continue
            record = convert(record)
            if record is None:
                continue
        out.append(ReviewDecision.from_record(record))
    return out
