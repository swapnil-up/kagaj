"""Verification engine — math audit of DoFE approval tables.

Invariants (see MIGRATION_NOTES.md §8.3), checked per (section, name):

    Male + Female                         = Total          (each channel group)
    RA + IndivNew + GtoG + IndivReEntry
        + Legalization                    = Total w/ ReEntry   (each gender)
    Total w/ ReEntry − Individual-ReEntry = Total w/o ReEntry  (each gender)

plus the section-level check:

    Σ detail rows = printed Total row     (each of the 21 numeric columns)

Counts are integer people, so exact equality is required.
"""

from .model import (
    GENDERS,
    GROUP_LABELS,
    RE_ENTRY_CHANNELS,
    WIDE_SECTIONS,
    WideRow,
    channels_for,
)


class Check:
    """One failed invariant (or a passing one, when ``ok`` is True)."""

    def __init__(self, section: str, name: str, kind: str, detail: str,
                 computed: int, stated: int, page: int = 0, ok: bool | None = None):
        self.section = section
        self.name = name
        self.kind = kind
        self.detail = detail
        self.computed = computed
        self.stated = stated
        self.page = page
        self._ok = ok

    @property
    def diff(self) -> int:
        return self.computed - self.stated

    @property
    def ok(self) -> bool:
        if self._ok is not None:
            return self._ok
        return self.computed == self.stated

    def __repr__(self):
        flag = "ok" if self.ok else "FAIL"
        return (f"<{flag} [{self.section}] {self.name}: {self.kind} {self.detail} "
                f"computed={self.computed} stated={self.stated} diff={self.diff}>")


class Report:
    def __init__(self, checks: list["Check"], total: int = 0):
        self.checks = checks          # failures only
        self.total = total or len(checks)

    @property
    def failures(self) -> list[Check]:
        return self.checks

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        nf = len(self.failures)
        return f"{self.total} checks: {self.total - nf} ok, {nf} FAILED"


def _check_row(row: WideRow) -> list[Check]:
    out: list[Check] = []
    chans = channels_for(len(row.nums))
    if len(row.nums) != len(chans) * 3:
        out.append(Check(row.section, row.name, "short_row",
                         f"{len(row.nums)} numeric cells (expected {len(chans) * 3})",
                         len(row.nums), len(chans) * 3, row.page))
        return out
    # Male + Female = Total, per channel group.
    for g, chan in enumerate(chans):
        m, f, t = row.nums[g * 3], row.nums[g * 3 + 1], row.nums[g * 3 + 2]
        if m + f != t:
            out.append(Check(row.section, row.name, "male_female_total",
                             GROUP_LABELS[chan], m + f, t, row.page))
    components = chans[:-2]
    with_c, without_c = chans[-2], chans[-1]
    re_c = next((c for c in chans if c in RE_ENTRY_CHANNELS), None)
    # Component channels sum to Total-with-ReEntry, per gender.
    for gender in GENDERS:
        parts = sum(row.value(c, gender) for c in components)
        with_re = row.value(with_c, gender)
        if parts != with_re:
            out.append(Check(row.section, row.name, "components_with_reentry",
                             gender, parts, with_re, row.page))
        if re_c:
            without_re = row.value(without_c, gender)
            if with_re - row.value(re_c, gender) != without_re:
                out.append(Check(row.section, row.name, "without_reentry",
                                 gender, with_re - row.value(re_c, gender),
                                 without_re, row.page))
    return out


def verify(result) -> Report:
    checks: list[Check] = []
    total = 0
    for row in result.wide_rows:
        if not row.is_total:
            nchans = len(channels_for(len(row.nums)))
            total += nchans + 6
            checks.extend(_check_row(row))

    # Section-level: Σ detail rows vs printed Total row, per section.
    sections = {r.section for r in result.wide_rows}
    for section in sorted(sections):
        if section not in WIDE_SECTIONS:
            continue
        detail = [r for r in result.wide_rows
                  if r.section == section and not r.is_total]
        totals = [r for r in result.wide_rows
                  if r.section == section and r.is_total]
        if not totals:
            total += 1
            checks.append(Check(section, "*", "missing_total",
                                "no printed Total row", 0, 0, ok=False))
            continue
        ncols = max((len(r.nums) for r in detail), default=0)
        chans = channels_for(ncols)
        colsum = [sum(r.nums[i] for r in detail if i < len(r.nums))
                  for i in range(ncols)]
        for t in totals:
            # Only compare columns the total row actually fills (nonzero).
            for i, stated in enumerate(t.nums[:ncols]):
                if stated == 0:
                    continue
                total += 1
                chan = chans[i // 3]
                gender = GENDERS[i % 3]
                if colsum[i] != stated:
                    checks.append(Check(
                        section, "*", "section_total",
                        f"{GROUP_LABELS[chan]}.{gender}",
                        colsum[i], stated, t.page))
    return Report(checks, total)
