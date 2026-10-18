"""Deterministic field parsers for KUKL schedule cells.

The whole point of the geometry pipeline is that the risky fields — DMA codes,
delivery days, and time windows — never touch an LLM. They are numeric/regular,
so they are parsed here with fixed rules. The only fuzz left for Gemini is
transliterating area names.

Time handling maps Nepali period words to 24-hour clocks and resolves a
start/end pair into ``(start_min, duration_min)``, absorbing cross-midnight
windows (including explicit "tomorrow" markers).
"""

from __future__ import annotations

import re

DEVA_DIGITS = {ord(d): str(i) for i, d in enumerate("०१२३४५६७८९")}
# Common OCR confusions for the zero glyph.
DEVA_DIGITS[ord("°")] = "0"

PERIODS = {
    "morning": ("बिहान", "विहान", "बिहानको", "सকাল", "सकाल", "सকালको"),
    "afternoon": ("दिउँसो", "दिउसो", "दिउंसो", "दिउसोको", "दिउंसोको"),
    "evening": ("बेलुका", "बेलुकी", "साँझ", "साझ", "सन्ध्या"),
    "night": ("राति", "रात", "रातिको", "रात्री"),
}
TOMORROW = ("भोलि", "भोलिपल्ट", "भोलिपल्टका", "भोलिपल्टको")

# number[sep]number  (e.g. ६:००, 7.00, ५।००) or  number बजे  or  bare number
_TIME_HM = re.compile(r"(\d{1,2})\s*[:.।]\s*(\d{1,2})")
_TIME_BAJE = re.compile(r"(\d{1,2})\s*बजे")
_TIME_BARE = re.compile(r"(?<!\d)(\d{1,2})(?!\d)")
_DMA = re.compile(r"\d{1,2}(?:\.\d{1,2})+")


def to_ascii_digits(text: str) -> str:
    return (text or "").translate(DEVA_DIGITS)


def _period_of(text: str) -> str | None:
    for name, words in PERIODS.items():
        if any(w in text for w in words):
            return name
    return None


def parse_days(text: str) -> tuple[list[int], bool]:
    """Return ``(days, repaired)``. ``repaired`` flags merged OCR digit runs."""
    s = to_ascii_digits(text or "")
    if not s.strip():
        return [], False
    days: list[int] = []
    repaired = False
    for token in re.split(r"[,;/\s।\-]+", s):
        token = re.sub(r"\D", "", token)
        if not token:
            continue
        if len(token) <= 2:
            days.append(int(token))
            continue
        # merged run like "1014" or "1211" -> split into 1-2 digit days
        parts = _split_days(token)
        if parts:
            repaired = True
            days.extend(parts)
    out = sorted({d for d in days if 1 <= d <= 32})
    return out, repaired


def _split_days(token: str) -> list[int] | None:
    """Greedily split a digit run into 1-2 digit values valid as days 1..32."""
    res: list[int] = []
    i = 0
    while i < len(token):
        for size in (2, 1):
            chunk = token[i:i + size]
            if len(chunk) == size and 1 <= int(chunk) <= 32:
                res.append(int(chunk))
                i += size
                break
        else:  # pragma: no cover - unreachable for well-formed input
            return None
    return res or None


def parse_dma(text: str) -> str | None:
    m = _DMA.search(to_ascii_digits(text or ""))
    return m.group(0) if m else None


def parse_clock(text: str) -> dict | None:
    """Extract ``{hour, minute, period}`` from a cell; period may be None."""
    s = _normalize_clock_text(text)
    period = _period_of(text or "")
    m = _TIME_HM.search(s) or _TIME_BAJE.search(s) or _TIME_BARE.search(s)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.re.groups >= 2 and m.group(2) is not None else 0
    if hour > 23:
        return None
    return {"hour": hour, "minute": minute, "period": period}


def _normalize_clock_text(text: str) -> str:
    """ASCII-ise digits and repair OCR spacing around separators/digits."""
    s = to_ascii_digits(text or "")
    s = re.sub(r"\s*([:.])\s*", r"\1", s)
    s = re.sub(r"(?<=\d)\s+(?=\d)", "", s)
    return s


def hour_candidates(clock: dict) -> list[int]:
    """Plausible 24-hour values for a clock given its period word."""
    h = clock["hour"]
    period = clock["period"]
    if period == "morning":
        return [h if h <= 12 else h]
    if period == "afternoon":
        return [h if h >= 12 else h + 12]
    if period == "evening":
        return [h if h >= 12 else h + 12]
    if period == "night":
        if h == 12:
            return [0]
        if h <= 4:
            return [h]
        return [h if h >= 12 else h + 12]
    base = h % 12
    return [base, base + 12]


def resolve_window(from_text: str, to_text: str) -> dict:
    """Resolve a start/end cell pair into a normalised window.

    Returns ``{start, duration, time_from, time_to, crosses_midnight, flags}``
    where ``start``/``duration`` are minutes and ``time_from``/``time_to`` are
    ``HH:MM`` strings. Empty/None inputs yield ``time_from``/``time_to`` None.
    """
    flags: list[str] = []
    start_clock = parse_clock(from_text or "")
    end_clock = parse_clock(to_text or "")

    if start_clock is None and end_clock is None:
        return {"start": None, "duration": None, "time_from": None,
                "time_to": None, "crosses_midnight": False, "flags": ["time_missing"]}

    if start_clock is None or end_clock is None:
        only = start_clock or end_clock
        h = hour_candidates(only)[0]
        t = f"{h:02d}:{only['minute']:02d}"
        if start_clock is None:
            return {"start": None, "duration": None, "time_from": None,
                    "time_to": t, "crosses_midnight": False,
                    "flags": ["time_partial"]}
        return {"start": h * 60 + only["minute"], "duration": None,
                "time_from": t, "time_to": None, "crosses_midnight": False,
                "flags": ["time_partial"]}

    if start_clock["period"] is None:
        flags.append("period_inferred")
    if end_clock["period"] is None:
        flags.append("period_inferred")

    tomorrow = any(w in (to_text or "") for w in TOMORROW)
    starts = hour_candidates(start_clock)
    ends = hour_candidates(end_clock)
    smin = start_clock["minute"]
    emin = end_clock["minute"]

    if not tomorrow and smin == emin and starts == ends:
        h0 = starts[0] * 60 + smin
        return {"start": h0, "duration": 0, "time_from": _fmt(h0),
                "time_to": _fmt(h0), "crosses_midnight": False,
                "flags": flags + ["time_zero_length"]}

    best: tuple[int, int] | None = None  # (duration, end_min)
    for a in starts:
        a_min = a * 60 + smin
        for b in ends:
            b_min = b * 60 + emin + (1440 if tomorrow else 0)
            d = b_min - a_min
            if d <= 0:
                d += 1440
            if d <= 0:
                continue
            if best is None or d < best[0]:
                best = (d, b_min)
    if best is None:
        h0 = starts[0] * 60 + smin
        return {"start": h0, "duration": 0, "time_from": _fmt(h0),
                "time_to": _fmt(h0), "crosses_midnight": False,
                "flags": flags + ["time_zero_length"]}

    duration, end_min_total = best
    start_min = end_min_total - duration
    crosses = (end_min_total % 1440) <= (start_min % 1440)
    if duration == 0:
        flags.append("time_zero_length")
    if duration > 18 * 60:
        flags.append("time_implausible_long")
    return {
        "start": start_min % 1440,
        "duration": duration,
        "time_from": _fmt(start_min),
        "time_to": _fmt(end_min_total),
        "crosses_midnight": crosses,
        "flags": flags,
    }


def _fmt(total_min: int) -> str:
    total_min %= 1440
    return f"{total_min // 60:02d}:{total_min % 60:02d}"
