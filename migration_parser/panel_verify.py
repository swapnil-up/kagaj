"""Panel-wide verification — independent math audit of ``datasets/labour-migration/panel.csv``.

``verify.py`` checks the tables at extraction time (on the in-memory wide rows).
This module re-checks the *melted* panel, so it also guards against melt/
normalisation regressions. Channels are canonicalised first (the panel stores the
raw printed names) via ``datasets/labour-migration/channels.json``. Invariants:

    Male + Female                       = Total           (each channel)
    Σ component channels (per gender)   = Total with Re-Entry
    Total with Re-Entry − Re-entry      = Total without Re-Entry
    Σ detail rows                       = printed Total    (each channel × gender)

Returns a list of ``PanelCheck`` failures; empty means the panel is internally
consistent.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from . import normalize


@dataclass
class PanelCheck:
    doc_id: str
    section: str
    name: str
    channel: str
    gender: str
    kind: str
    computed: int
    stated: int

    @property
    def diff(self) -> int:
        return self.computed - self.stated

    def __str__(self) -> str:
        return (f"[{self.doc_id}/{self.section}] {self.name} {self.channel}.{self.gender} "
                f"{self.kind}: computed={self.computed} stated={self.stated} "
                f"diff={self.diff}")


def verify_panel(rows: list[dict]) -> list[PanelCheck]:
    classes = normalize.channel_classes()
    components = {c for c, k in classes.items() if k == "component"}

    # canonical value lookup: (doc, section, row_type, name, canon_chan, gender)
    val: dict[tuple, int] = defaultdict(int)
    for r in rows:
        canon = normalize.canonical_channel(r["channel"])["canonical"]
        key = (r["doc_id"], r["section"], r["row_type"], r["name"], canon, r["gender"])
        val[key] += int(r["count"])

    def get(doc, sec, rt, name, chan, g):
        return val.get((doc, sec, rt, name, chan, g))

    fails: list[PanelCheck] = []
    entities = {(r["doc_id"], r["section"], r["name"])
                for r in rows if r["row_type"] == "detail"}

    for doc, sec, name in entities:
        chans = {normalize.canonical_channel(r["channel"])["canonical"]
                 for r in rows if r["row_type"] == "detail"
                 and r["doc_id"] == doc and r["section"] == sec and r["name"] == name}
        for chan in chans:
            m = get(doc, sec, "detail", name, chan, "male")
            f = get(doc, sec, "detail", name, chan, "female")
            t = get(doc, sec, "detail", name, chan, "total")
            if None not in (m, f, t) and m + f != t:
                fails.append(PanelCheck(doc, sec, name, chan, "total",
                                        "male_female_total", m + f, t))
        for g in ("male", "female", "total"):
            comp = sum(get(doc, sec, "detail", name, c, g)
                       for c in chans & components
                       if get(doc, sec, "detail", name, c, g) is not None)
            wr = get(doc, sec, "detail", name, "total_with_reentry", g)
            if wr is not None and comp != wr:
                fails.append(PanelCheck(doc, sec, name, "total_with_reentry", g,
                                        "components_with_reentry", comp, wr))
            re = get(doc, sec, "detail", name, "individual_reentry", g)
            wo = get(doc, sec, "detail", name, "total_without_reentry", g)
            if None not in (wr, re, wo) and wr - re != wo:
                fails.append(PanelCheck(doc, sec, name, "total_without_reentry", g,
                                        "without_reentry", wr - re, wo))

    # Σ detail = printed Total, per (doc, section, canonical channel, gender).
    totals: dict[tuple, int] = defaultdict(int)
    for r in rows:
        if r["row_type"] == "total":
            canon = normalize.canonical_channel(r["channel"])["canonical"]
            totals[(r["doc_id"], r["section"], canon, r["gender"])] += int(r["count"])
    detail_sum: dict[tuple, int] = defaultdict(int)
    for r in rows:
        if r["row_type"] == "detail":
            canon = normalize.canonical_channel(r["channel"])["canonical"]
            detail_sum[(r["doc_id"], r["section"], canon, r["gender"])] += int(r["count"])
    for (doc, sec, chan, g), stated in totals.items():
        got = detail_sum.get((doc, sec, chan, g), 0)
        if got != stated:
            fails.append(PanelCheck(doc, sec, "Total", chan, g,
                                    "section_total", got, stated))
    return fails
