"""Entity + period normalisation for the migration panel.

Canonical reference data lives in ``datasets/labour-migration/{countries,districts,fiscal_years}.json``
(tracked). This module resolves raw, source-specific names to canonical entities
and derives a canonical fiscal year for every row, without mutating the raw data
(provenance is preserved by keeping the original ``name``/``period_bs`` columns).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_ENTITIES_DIR = Path(__file__).resolve().parent.parent / "datasets" / "labour-migration"

# Content-id -> fiscal year, for annual documents whose parser could not read the
# BS period from the page (older layouts). Cropped from the manifest titles.
DOC_FISCAL_YEAR = {
    "89": "2073/74",
    "32": "2079/80",
    "33": "2078/79",
    "34": "2077/78",
    "35": "2076/77",
    "20": "2081/82",
    "29": "2080/81",
    "278": "2082/83",
    "332": "2083/84",
    "258": "2082/83",
    "37": "2081/82",
    "90": "2076/77",
    "91": "2077/78",
    "92": "2079/80",
    "94": "2073/74",
    "report2020_annex_IX": "2074/75",
    "report2020_annex_X": "2074/75",
    "report2020_annex_XI": "2074/75",
    "report2020_annex_XII": "2074/75",
    "report2020_annex_XIII": "2075/76",
    "preapproval_030": "2075/76",
    "preapproval_031": "2075/76",
    "preapproval_032": "2073/74",
}


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).casefold()


@lru_cache(maxsize=None)
def _load_json(name: str):
    return json.loads((_ENTITIES_DIR / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _country_index():
    idx: dict[str, dict] = {}
    for e in _load_json("countries.json"):
        idx[_fold(e["name"])] = e
        for a in e.get("aliases", []):
            idx[_fold(a)] = e
    return idx


@lru_cache(maxsize=None)
def _district_index():
    idx: dict[str, dict] = {}
    for e in _load_json("districts.json"):
        idx[_fold(e["name"])] = e
        for a in e.get("aliases", []):
            idx[_fold(a)] = e
    return idx


def _fiscal_data():
    return _load_json("fiscal_years.json")


def _compact_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").casefold())


@lru_cache(maxsize=None)
def _country_compact_index():
    """Map punctuation/space-stripped names to entities, dropping collisions.

    Some PDF table extractors return a country cell with the spaces removed
    (``SaudiArabia``); the exact-fold index cannot resolve those. Ambiguous
    compact keys are omitted rather than guessed.
    """
    idx: dict[str, dict] = {}
    ambiguous: set[str] = set()
    for e in _load_json("countries.json"):
        for label in (e["name"], *e.get("aliases", [])):
            key = _compact_key(label)
            if not key:
                continue
            prev = idx.get(key)
            if prev is not None and prev["name"] != e["name"]:
                ambiguous.add(key)
            else:
                idx[key] = e
    for key in ambiguous:
        idx.pop(key, None)
    return idx


def canonical_country(raw: str) -> dict | None:
    """Return the canonical country record for ``raw`` (or None if unknown)."""
    if not raw:
        return None
    e = _country_index().get(_fold(raw))
    return e or _country_compact_index().get(_compact_key(raw))


@lru_cache(maxsize=None)
def _country_word_vocab():
    words: set[str] = set()
    for e in _load_json("countries.json"):
        for label in (e["name"], *e.get("aliases", [])):
            words.update(w.lower() for w in re.findall(r"[A-Za-z]+", label))
    words.update({"and", "of", "the", "from", "eps", "pdr"})
    words = {w for w in words if len(w) >= 2}
    by_first: dict[str, tuple[str, ...]] = {}
    for w in words:
        by_first.setdefault(w[0], []).append(w)
    return {k: tuple(sorted(v, key=len, reverse=True))
            for k, v in by_first.items()}


def restore_country_spacing(raw: str) -> str:
    """Re-insert spaces lost by PDF table-cell extraction.

    PyMuPDF's table extractor can concatenate multi-word Latin cells
    (``BruneiDarussalam``). Split against the country-name/alias vocabulary;
    fall back to camel-case boundaries for labels outside that vocabulary.
    Never invents characters: unmatched values are returned unchanged.
    """
    if not raw or not re.fullmatch(r"[A-Za-z ]+", raw):
        return raw
    compact = raw.replace(" ", "")
    lower = compact.lower()
    vocab = _country_word_vocab()
    best: list[tuple[int, int, tuple[str, ...]] | None] = [None] * (len(lower) + 1)
    best[0] = (0, 0, ())
    for i in range(len(lower)):
        prev = best[i]
        if prev is None:
            continue
        for word in vocab.get(lower[i], ()):
            if not lower.startswith(word, i):
                continue
            j = i + len(word)
            cand = (prev[0] + len(word) ** 2, prev[1] + 1,
                    prev[2] + (compact[i:j],))
            cur = best[j]
            if cur is None or cand[:2] > cur[:2]:
                best[j] = cand
    if best[-1] is not None and best[-1][1] > 1:
        return " ".join(best[-1][2])
    camel = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", compact)
    return camel


def canonical_district(raw: str) -> dict | None:
    if not raw:
        return None
    return _district_index().get(_fold(raw))


def fiscal_years() -> dict[str, dict]:
    return {e["bs"]: e for e in _fiscal_data()["fiscal_years"]}


def months() -> list[dict]:
    return _fiscal_data()["months"]


_MONTH_BY_NP: dict[str, dict] | None = None


def _month_index():
    global _MONTH_BY_NP
    if _MONTH_BY_NP is None:
        _MONTH_BY_NP = {}
        for m in months():
            for np in m["np"]:
                _MONTH_BY_NP[_fold(np)] = m
            _MONTH_BY_NP[_fold(m["name"])] = m
    return _MONTH_BY_NP


def parse_bs_month(period_bs: str):
    """Parse a monthly ``period_bs`` like ``"2082 असोज"`` -> (year, month_dict).

    Returns ``(None, None)`` when the string is not a recognisable BS month.
    """
    if not period_bs:
        return None, None
    m = re.match(r"^\s*(\d{4})\s+(\S+)", period_bs)
    if not m:
        return None, None
    year = int(m.group(1))
    month = _month_index().get(_fold(m.group(2)))
    return (year, month) if month else (None, None)


def fiscal_year_of_month(year: int, month_index: int) -> str:
    """BS fiscal year label (Shrawan 1 .. Ashadh end) for a BS year+month."""
    if month_index >= 4:
        return f"{year}/{str(year + 1)[-2:]}"
    return f"{year - 1}/{str(year)[-2:]}"


def normalize_fy_label(period_bs: str) -> str | None:
    """Normalise an annual BS label (``"2079-80"``, ``"२०७९/८०"``) -> ``"2079/80"``."""
    if not period_bs:
        return None
    digits = period_bs.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    m = re.match(r"^\s*(\d{4})\s*[/-]\s*(\d{2,4})", digits)
    if not m:
        return None
    start = int(m.group(1))
    end2 = m.group(2)[-2:]
    return f"{start}/{end2}"


def fiscal_year_for_row(doc_id: str, period_bs: str) -> str | None:
    """Resolve the canonical fiscal year for a row."""
    fy = normalize_fy_label(period_bs)
    if fy:
        return fy
    year, month = parse_bs_month(period_bs)
    if year and month:
        return fiscal_year_of_month(year, month["index"])
    return DOC_FISCAL_YEAR.get(doc_id)


def fiscal_year_for_ad(label: str) -> str | None:
    """Map an AD fiscal-year label (``"2019/20"``) to the canonical BS label.

    Matches the label's start year against the ``ad_start`` recorded in
    ``fiscal_years.json`` (e.g. ``2019`` -> ``"2076/77"``). Returns ``None`` if
    the label is unparseable or the year is outside the table.
    """
    if not label:
        return None
    m = re.match(r"\s*(\d{4})", label)
    if not m:
        return None
    year = m.group(1)
    for e in _fiscal_data()["fiscal_years"]:
        if str(e.get("ad_start", "")).startswith(year):
            return e["bs"]
    return None


# Doc 332 clips the country column to ~22 pt. ``get_texttrace`` still exposes
# the full drawn strings, so these serial-scoped overrides recover the five
# clipped labels without guessing from counts. Serial 55 is a second Seychelles
# row in the source; reconcile sums it with SN 34 under the intra-doc merge rule.
CLIPPED_COUNTRY_OVERRIDES = {
    ("332", "9"): ("South Korea", ""),
    ("332", "14"): ("Bulgaria", ""),
    ("332", "30"): ("North Macedonia", ""),
    ("332", "55"): ("Seychelles", "source also prints a separate Seychelles row (SN 34); "
                    "the two rows are summed under the intra-document merge rule"),
    ("332", "76"): ("Republic of the Congo", ""),
}


def _serial_key(sn) -> str:
    try:
        return str(int(float(sn)))
    except (TypeError, ValueError):
        return str(sn or "").strip()


def normalize_name(section: str, name: str, doc_id: str | None = None,
                   sn=None) -> dict:
    """Resolve a panel ``name`` given its ``section``.

    Returns a dict with ``canonical``, ``resolved``, and optional ``iso3`` /
    ``province`` / ``note`` / ``kind``.
    """
    if section == "country":
        override = CLIPPED_COUNTRY_OVERRIDES.get(
            (str(doc_id or ""), _serial_key(sn)))
        if override and _fold(name) in {"republic o", "republi"}:
            canonical, note = override
            e = canonical_country(canonical)
            if e is not None:
                out = {"canonical": e["name"], "resolved": True,
                       "note": note or "clipped label resolved from PDF text trace"}
                if e.get("iso3"):
                    out["iso3"] = e["iso3"]
                return out
        e = canonical_country(name)
        if e is None:
            return {"canonical": name, "resolved": False, "kind": "unknown"}
        out = {"canonical": e["name"], "resolved": e.get("resolved", True)}
        if e.get("iso3"):
            out["iso3"] = e["iso3"]
        if e.get("note"):
            out["note"] = e["note"]
        if e.get("kind"):
            out["kind"] = e["kind"]
        return out
    if section == "district":
        e = canonical_district(name)
        if e is None:
            return {"canonical": name, "resolved": False, "kind": "unknown"}
        out = {"canonical": e["name"], "resolved": e.get("resolved", True), "province": e["province"]}
        if e.get("note"):
            out["note"] = e["note"]
        return out
    return {"canonical": name, "resolved": True}


@lru_cache(maxsize=None)
def _channel_data():
    return _load_json("channels.json")


@lru_cache(maxsize=None)
def _channel_index():
    idx: dict[str, dict] = {}
    for e in _channel_data()["source_map"]:
        idx[e["source"]] = e
    return idx


def channel_map() -> dict:
    """Mapping from the archive panel's ``approval_type`` to modern channels.

    Currently a documented ``null/TBD`` stub (the two axes never overlap in the
    printed data, so the correspondence is unverifiable) — see ``channels.json``.
    """
    return dict(_channel_data().get("channel_map", {}))


def canonical_channels() -> dict[str, dict]:
    """Canonical channel metadata, keyed by canonical name."""
    return {e["name"]: e for e in _channel_data()["canonical_channels"]}


def channel_classes() -> dict[str, str]:
    """Map each canonical channel to its class (component/aggregate/measure)."""
    return {e["name"]: e["class"] for e in _channel_data()["canonical_channels"]}


def channel_reviewed() -> dict[str, bool]:
    """Map each canonical channel to whether its cross-template equivalence is
    independently reviewed (``false`` flags a single-analyst judgment call)."""
    return {e["name"]: e.get("reviewed", True) for e in _channel_data()["canonical_channels"]}


def canonical_channel(channel: str) -> dict:
    """Resolve a raw channel (as printed across templates) to the canonical one.

    Returns ``{canonical, class, label, note?}``. Unknown channels map to
    themselves with ``class="unknown"``.
    """
    src = _channel_index().get(channel)
    if src is None:
        return {"canonical": channel, "class": "unknown", "label": channel,
                "reviewed": False}
    name = src["canonical"]
    meta = canonical_channels().get(name, {})
    out = {"canonical": name, "class": meta.get("class", "unknown"),
           "label": meta.get("label", name), "reviewed": meta.get("reviewed", True)}
    if src.get("note"):
        out["note"] = src["note"]
    return out


@lru_cache(maxsize=None)
def reconciliation() -> dict:
    return _load_json("reconciliation.json")


_OVERRIDES: dict[str, dict] | None = None


def override_for(doc_id: str) -> dict | None:
    global _OVERRIDES
    if _OVERRIDES is None:
        _OVERRIDES = {o["doc_id"]: o for o in reconciliation().get("overrides", [])}
    return _OVERRIDES.get(doc_id)


def reconciled_fiscal_year(doc_id: str, fiscal_year: str) -> str:
    """Apply any documented period override (e.g. Annex Table X header typo)."""
    o = override_for(doc_id)
    if o and fiscal_year == o.get("printed_fiscal_year"):
        return o["reconciled_fiscal_year"]
    return fiscal_year


def doc_granularity(doc_type: str, channel_class: str = "") -> str:
    """Canonical aggregation granularity: month | year | measure | ''."""
    if channel_class == "measure":
        return "measure"
    return reconciliation()["granularity"].get(doc_type, "")


def dedup_key_columns() -> list[str]:
    return reconciliation()["dedup_key"]
