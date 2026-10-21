"""Conflict records for the CID review workbench.

One :class:`Conflict` combines the census evidence for an unknown
``(font, cid)`` with the store value, the CID-wide derive fallback, and ranked
OCR candidates. Verdicts use the shared Devanagari key so equivalent digits
and matra encodings compare equal while visual-order differences still show.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from kagaj_core.devanagari import canonical_key, validate

from .decode import census
from .mappings import get_value


@dataclass
class Conflict:
    font: str
    cid: int
    store_value: str | None
    derive_value: str | None
    ocr_candidates: list[dict]
    glyph_bbox: tuple[float, float, float, float] | None
    word_bbox: tuple[float, float, float, float] | None
    page: int | None
    context: str
    n_occ: int
    page_range: str
    verdict: str
    agreement: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _key(text: str | None) -> str:
    return canonical_key(text or "", drop_joiners=False)


def _issue_codes(text: str | None) -> list[str]:
    if not text:
        return []
    return [issue.code for issue in validate(text)]


def _bbox(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    return tuple(float(x) for x in value)


def _candidate(word: str, count: int = 0, pages=None, bbox=None) -> dict:
    return {
        "word": "" if word is None else str(word),
        "count": int(count),
        "pages": sorted({int(p) for p in (pages or []) if p is not None}),
        "bbox": _bbox(bbox),
    }


def _rank(candidates) -> list[dict]:
    return sorted(candidates,
                  key=lambda c: (-int(c.get("count") or 0), c.get("word") or ""))


def _from_reads(reads: dict, counts: dict) -> dict:
    grouped: dict[str, dict[int, dict[str, dict]]] = {}
    for font, cids in reads.items():
        for raw_cid, entries in (cids or {}).items():
            by_word = grouped.setdefault(str(font), {}).setdefault(
                int(raw_cid), {})
            for entry in entries or []:
                word = entry.get("word")
                if word is None:
                    continue
                cand = by_word.setdefault(word, {
                    "word": word, "count": 0, "pages": [], "bbox": None,
                    "_n": 0,
                })
                cand["_n"] += 1
                if entry.get("page") is not None:
                    cand["pages"].append(entry["page"])
                if entry.get("bbox") is not None:
                    cand["bbox"] = entry["bbox"]

    for font, cids in counts.items():
        for raw_cid, words in (cids or {}).items():
            by_word = grouped.setdefault(str(font), {}).setdefault(
                int(raw_cid), {})
            for word, count in (words or {}).items():
                cand = by_word.setdefault(word, {
                    "word": word, "count": 0, "pages": [], "bbox": None,
                    "_n": 0,
                })
                cand["count"] = int(count)

    out: dict[str, dict[int, list[dict]]] = {}
    for font, cids in grouped.items():
        for cid, by_word in cids.items():
            candidates = []
            for cand in by_word.values():
                if not cand["count"]:
                    cand["count"] = cand["_n"]
                candidates.append(_candidate(
                    cand["word"], cand["count"], cand["pages"], cand["bbox"]))
            out.setdefault(font, {})[cid] = _rank(candidates)
    return out


def _from_counts(ocr: dict) -> dict:
    out: dict[str, dict[int, list[dict]]] = {}
    for font, cids in (ocr or {}).items():
        for raw_cid, words in (cids or {}).items():
            cid = int(raw_cid)
            candidates = []
            if isinstance(words, dict):
                for word, count in words.items():
                    candidates.append(_candidate(word, count))
            elif isinstance(words, list):
                for item in words:
                    if isinstance(item, dict):
                        candidates.append(_candidate(
                            item.get("word", ""), item.get("count", 0),
                            item.get("pages"), item.get("bbox")))
                    else:
                        candidates.append(_candidate(str(item)))
            out.setdefault(str(font), {})[cid] = _rank(candidates)
    return out


def _index_ocr(ocr: dict) -> dict:
    if not isinstance(ocr, dict):
        return {}
    if "reads" in ocr or "counts" in ocr:
        return _from_reads(ocr.get("reads") or {}, ocr.get("counts") or {})
    return _from_counts(ocr)


def _page_list(rec: dict) -> list[int]:
    return sorted({int(p) for p in rec.get("pages", []) if p is not None})


def _page_range(rec: dict, pages: list[int]) -> str:
    if rec.get("range"):
        return str(rec["range"])
    if pages:
        return f"p{pages[0]}\u2013p{pages[-1]}"
    return ""


def _verdict(value: str | None, candidates: list[dict], n_occ: int,
             value_issues: list[str]) -> tuple[str, dict]:
    key = _key(value)
    agree = disagree = evidence = 0
    for candidate in candidates:
        candidate_key = _key(candidate["word"])
        if not candidate_key:
            continue
        count = candidate["count"]
        if not key:
            evidence += count
        elif key in candidate_key:
            agree += count
        else:
            disagree += count
    no_ocr = max(0, n_occ - (agree + disagree + evidence))

    if not value:
        verdict = "missing"
    elif not candidates:
        verdict = "no-ocr"
    elif value_issues:
        verdict = "disagree"
    elif agree > disagree:
        verdict = "agree"
    elif disagree > agree:
        verdict = "disagree"
    elif no_ocr:
        verdict = "no-ocr"
    else:
        verdict = "tie"

    return verdict, {
        "agree": agree,
        "disagree": disagree,
        "evidence": evidence,
        "no_ocr": no_ocr,
        "value_valid": not value_issues,
        "value_issues": value_issues,
    }


def build_conflicts(doc, store: dict, ocr_counts: dict, *, pages=None,
                    census_result: dict | None = None) -> list[Conflict]:
    """Build conflict records from a census and OCR evidence.

    ``ocr_counts`` accepts either the full :func:`cidmap.ocr.cross_check`
    result (``reads`` + ``counts``) or a plain ``{font: {cid: {word: count}}}``
    mapping. ``census_result`` is an injection point for tests; otherwise the
    document is scanned with :func:`cidmap.decode.census`.
    """
    cen = census_result if census_result is not None else census(doc)
    return build_conflicts_from_census(cen, store, ocr_counts, pages=pages)


def build_conflicts_from_census(cen: dict, store: dict, ocr_data: dict, *,
                                pages=None) -> list[Conflict]:
    ocr = _index_ocr(ocr_data)
    page_filter = {int(p) for p in pages} if pages is not None else None
    out: list[Conflict] = []

    for font in sorted(cen):
        for raw_cid in sorted(cen[font]):
            cid = int(raw_cid)
            rec = cen[font][raw_cid]
            rec_pages = _page_list(rec)
            if page_filter is not None and not (set(rec_pages) & page_filter):
                continue

            candidates = list(ocr.get(str(font), {}).get(cid, []))
            if page_filter is not None:
                candidates = [
                    c for c in candidates
                    if not c["pages"] or set(c["pages"]) & page_filter
                ]

            store_value = store.get("fonts", {}).get(font, {}).get(cid)
            by_cid = store.get("cids", {})
            derive_entry = by_cid.get(cid)
            if derive_entry is None:
                derive_entry = by_cid.get(str(cid), {})
            derive_value = derive_entry.get("")
            value = get_value(store, font, cid)
            n_occ = int(rec.get("count") or 0)
            value_issues = _issue_codes(value)
            verdict, agreement = _verdict(
                value, candidates, n_occ, value_issues)
            agreement["derive_issues"] = _issue_codes(derive_value)

            samples = rec.get("samples") or []
            sample = samples[0] if samples else {}
            contexts = rec.get("contexts") or []
            context = contexts[0] if contexts else ""
            out.append(Conflict(
                font=font,
                cid=cid,
                store_value=store_value,
                derive_value=derive_value,
                ocr_candidates=candidates,
                glyph_bbox=_bbox(sample.get("bbox")),
                word_bbox=candidates[0]["bbox"] if candidates else None,
                page=sample.get("page"),
                context=context,
                n_occ=n_occ,
                page_range=_page_range(rec, rec_pages),
                verdict=verdict,
                agreement=agreement,
            ))

    return out
