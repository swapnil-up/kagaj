"""Domain model for DoFE labour-approval tables.

Reports come in two channel templates, both "S.N. + name + groups(× Male/
Female/Total)":

* **21-column** (modern monthly/yearly): 7 channel groups.
* **18-column** (older annual sanction statements): 6 channel groups — no
  G-to-G / Individual split.

See MIGRATION_NOTES.md §8.3.
"""

from dataclasses import dataclass, field

# Channel groups in column order (× Male/Female/Total).
CHANNEL_GROUPS = (
    "recruiting_agency",
    "individual_new",
    "g2g",
    "individual_reentry",
    "legalization",
    "total_with_reentry",
    "total_without_reentry",
)

# Older 18-column annual template (fewer, coarser channels).
CHANNEL_GROUPS_OLD = (
    "recruiting_agency",
    "new_entry",
    "legalized_entry",
    "re_entry",
    "total_with_reentry",
    "total_without_reentry",
)

# Keyed by numeric-column count.
TEMPLATES = {
    len(CHANNEL_GROUPS) * 3: CHANNEL_GROUPS,
    len(CHANNEL_GROUPS_OLD) * 3: CHANNEL_GROUPS_OLD,
}

GENDERS = ("male", "female", "total")

# Human labels as printed in the report header, used for verification messages.
GROUP_LABELS = {
    "recruiting_agency": "Recruiting Agency",
    "individual_new": "Individual-New",
    "g2g": "G-to-G",
    "individual_reentry": "Individual-ReEntry",
    "legalization": "Legalization",
    "new_entry": "New Entry",
    "legalized_entry": "Legalized Entry",
    "re_entry": "Re-Entry",
    "total_with_reentry": "Total with ReEntry",
    "total_without_reentry": "Total without ReEntry",
}

# Channels that denote re-entry, per template (used by the without-ReEntry check).
RE_ENTRY_CHANNELS = ("individual_reentry", "re_entry")

NUMERIC_COLS = len(CHANNEL_GROUPS) * 3  # 21 (modern default)
MAX_NUMERIC_COLS = 21

# Section kinds that use the wide layout.
WIDE_SECTIONS = ("country", "district")

# Section kinds that use the narrow 5-col layout (deferred, captured best-effort).
NARROW_SECTIONS = ("recruitment_agency", "skill")


def channels_for(ncols: int) -> tuple[str, ...]:
    """Return the channel-group tuple for a row with ``ncols`` numeric cells."""
    return TEMPLATES.get(ncols, CHANNEL_GROUPS)


@dataclass
class DocMeta:
    """Identity + period of one source document."""

    doc_id: str = ""              # content id or sha1 of the file
    filename: str = ""
    source_url: str = ""
    title: str = ""
    doc_type: str = ""            # single_month | cumulative | annual | institutional
    period_bs: str = ""           # e.g. "2083 Shrawan"
    period_ad_start: str = ""     # ISO date
    period_ad_end: str = ""       # ISO date

    def as_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "source_url": self.source_url,
            "title": self.title,
            "doc_type": self.doc_type,
            "period_bs": self.period_bs,
            "period_ad_start": self.period_ad_start,
            "period_ad_end": self.period_ad_end,
        }


@dataclass
class WideRow:
    """One extracted row from a wide section, before melting.

    ``nums`` holds 18 or 21 values in ``channels_for(len(nums)) × GENDERS``
    order (see ``TEMPLATES``).
    """

    section: str = ""             # country | district
    name: str = ""                # country or district name
    sn: str = ""                  # printed S.N. (may be blank on continuation)
    nums: list[int] = field(default_factory=list)
    is_total: bool = False
    page: int = 0

    def value(self, channel: str, gender: str) -> int:
        channels = channels_for(len(self.nums))
        if channel not in channels:
            return 0
        i = channels.index(channel) * 3 + GENDERS.index(gender)
        return self.nums[i] if i < len(self.nums) else 0


@dataclass
class ExtractResult:
    """Everything pulled from one PDF."""

    meta: DocMeta
    wide_rows: list[WideRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems
