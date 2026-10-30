"""Word-diff CID derive tool.

The human fills the review HTML with the full printed WORD that contains an
unknown CID (not the lone glyph). This module consumes ``cid_corrections.json``,
either the neutral review shape (``[{"key", "value", "undecodable", "data"}]``)
or the legacy ``[{"cid": N, "correct": "word"}]``, and recovers the exact Devanagari
cluster(s) each unknown CID maps to by diffing the typed word against the
PDF's *logical-order* text.

Why logical order: PyMuPDF's ``get_text('rawdict')`` returns each line in
reading order, with unmapped CIDs already rendered as raw control chars
(``\\x02`` = CID 2 etc.). Legacy glyph-census windows are clipped at +-3
glyphs and start mid-word, swallowing the matra/space of a neighbour. Matching
the typed word against logical lines turns ``आर्थिक वर्ष`` into
``आ⟦2⟧थ⟦4⟧क वष⟦4⟧`` — a joint solve of all unknowns at once reproduces the word.

Solving: for each window containing the target CID we assign *all* unknown
CIDs in the span 0-3 codepoints so the span equals the typed word, then also
try one "reph transpose" (swap an unknown with an adjacent literal) for
Devanagari re-ordering (``खच⟦3⟧`` -> खर्च). Results are unified across windows;
font scoping (same int CID -> ि here, र् there) is surfaced as a conflict.

CLI:
    redbook-env/bin/python -m redbook_parser.derive <pdf> <cid_corrections.json>
"""

import argparse
import json
import os
import re
from functools import lru_cache

from .extraction import extract_glyphs

CIDRE = re.compile(r"⟦(\d+)⟧")


def tokens_of(s: str) -> list[tuple[bool, int | str]]:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "⟦":
            j = s.index("⟧", i)
            out.append((True, int(s[i + 1:j])))
            i = j + 1
        else:
            out.append((False, s[i]))
            i += 1
    return out


def page_lines(page, glyphs) -> list[str]:
    """Logical-order lines for a page, unknown-glyph chars marked ⟦cid⟧.

    Unknown glyphs (c == "\\ufffd") are located by origin; each rawdict char
    whose (x, y) matches such a glyph becomes its CID mark.

    rawdict drops glyphs PyMuPDF cannot map into a span (measured: ~28% of the
    texttrace census, e.g. trailing reph र् drawn after its base). Those are
    re-inserted from the texttrace census at their x position, so a printed
    word like ``यथार्थ खर्च`` (= ``यथाथ⟦16⟧ खच⟦16⟧``) survives intact.
    """
    unknown_by_xy = {
        (round(g["origin"][0], 1), round(g["origin"][1], 1)): g["cid"]
        for g in glyphs if g["c"] == "\ufffd"
    }
    # texttrace census of ALL unknown glyphs, grouped by baseline (rounded y).
    dropped = {}
    for span in page.get_texttrace():
        for (u, glyph, origin, _bbox) in span.get("chars", []):
            if u == 65533:
                dropped.setdefault(round(origin[1], 0), []).append(
                    (origin[0], f"⟦{glyph}⟧", round(origin[0], 0)))
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            parts = []
            seen_xy = set()
            for c in (ch for s in line["spans"] for ch in s["chars"]):
                ox, oy = c["origin"][0], c["origin"][1]
                seen_xy.add((round(ox, 0), round(oy, 0)))
                cid = unknown_by_xy.get(
                    (round(ox, 1), round(oy, 1)))
                parts.append((ox, f"⟦{cid}⟧" if cid is not None else c["c"]))
            baseline = round(line["spans"][0]["chars"][0]["origin"][1], 0) \
                if line["spans"] and line["spans"][0]["chars"] else None
            if baseline is not None:
                for gx, mark, rx in dropped.get(baseline, []):
                    if (rx, baseline) not in seen_xy:
                        parts.append((gx, mark))
            parts.sort(key=lambda p: p[0])
            out.append("".join(p[1] for p in parts))
    return out


def all_lines(doc, max_pages: int | None = None):
    pages = range(len(doc)) if max_pages is None else range(min(max_pages, len(doc)))
    for pn in pages:
        glyphs = extract_glyphs(doc[pn], dedup=True)
        yield pn + 1, page_lines(doc[pn], glyphs)


def _lit(toks) -> int:
    return sum(len(t) for k, t in toks if not k)


def _unk(toks) -> int:
    return sum(1 for k, _ in toks if k)


def solve_line_tokens(toks, cid, word, cap: int = 200) -> list[tuple[int, str, list]]:
    """Char-precise slice search for ``cid`` inside one logical line.

    Windows are every contiguous token slice (down to single characters) that
    contains ``cid`` and is length-feasible, not just space-separated tokens.
    The redbook fuses Devanagari across space boundaries (halant joins, e.g.
    ``संघ ⟦51⟧तर`` = संघ स्तर), so only char-level slicing finds the answer.
    Returns [(value, span_string, slots)] deduplicated by span, capped.
    """
    n = len(toks)
    idxs = [i for i, (k, v) in enumerate(toks) if k and v == cid]
    hits: dict[str, tuple[int, str, list]] = {}
    # A real word contains few unknown glyphs; windows with many unknowns blow
    # up _compositions combinatorially (k=11, rem=11 -> 150k tuples) for no
    # extra signal. Cap unknowns per feasible window.
    max_unk = min(len(word), 6)
    for t in idxs:
        for a in range(t, -1, -1):
            sl_a = toks[a:t + 1]
            # Each unknown consumes >= 1 codepoint of the word; more unknowns
            # than word length can never fit.
            if _unk(sl_a) > max_unk:
                break
            if _lit(sl_a) > len(word):
                break
            for b in range(t + 1, min(n, t + 1 + len(word) + 4) + 1):
                sl = toks[a:b]
                if _unk(sl) > max_unk:
                    break
                lit = _lit(sl)
                if lit > len(word):
                    break
                if lit <= len(word) <= lit + 4 * _unk(sl):
                    for slots in solve_span(tuple(sl), word):
                        val = next((v for scid, v in slots if scid == cid), None)
                        if val is None:
                            continue
                        key = "".join(
                            ("⟦{}⟧".format(cv)) if k else cv for k, cv in sl)
                        if key not in hits:
                            hits[key] = (val, key, slots)
                            if len(hits) >= cap:
                                return list(hits.values())
                        break
    return list(hits.values())


def collect_windows(doc, cids, max_pages: int | None = None) -> dict[int, list[tuple[int, str]]]:
    """Return {cid: [(page, span), ...]}: 1-4 token spans containing ⟦cid⟧.

    Spans are deduplicated per cid (a repeated span from page N appears once),
    so the returned list stays small and page-fair. Retained for tests; derive
    now uses char-precise slicing (solve_line_tokens) instead.
    """
    cid_set = set(cids)
    found: dict = {c: {} for c in cids}   # span -> (page, span)
    for pn, lines in all_lines(doc, max_pages):
        for line in lines:
            toks = line.split(" ")
            for i, t in enumerate(toks):
                for cid in cid_set:
                    if f"⟦{cid}⟧" not in t:
                        continue
                    for a in range(max(0, i - 2), i + 1):
                        for b in range(i + 1, min(len(toks), i + 3) + 1):
                            span = " ".join(toks[a:b])
                            found[cid].setdefault(span, (pn, span))
    return {c: list(v.values()) for c, v in found.items()}


@lru_cache(maxsize=None)
def _compositions(total: int, parts: int) -> tuple[tuple[int, ...], ...]:
    """All ``parts``-tuples of 0..3 summing to ``total`` (lens for unknowns)."""
    if parts == 0:
        return ((),) if total == 0 else ()
    if total < 0 or total > 3 * parts:
        return ()
    out = []
    def rec(rem, k, acc):
        if k == 1:
            if rem <= 3:
                out.append(acc + (rem,))
            return
        for v in range(min(3, rem) + 1):
            rec(rem - v, k - 1, acc + (v,))
    rec(total, parts, ())
    return tuple(out)


def joint_match(tt, target: str):
    """All exact assignments of unknowns (0-3 codepoints) fitting target.

    Returns a list of ``[(cid, value), ...]`` slot-value pairs (one entry per
    unknown slot; the same int cid may appear on multiple slots and get values
    that differ across windows — that font-scoping signal is preserved).
    """
    unk = [i for i, (k, _) in enumerate(tt) if k]
    lit = sum(len(t) for k, t in tt if not k)
    rem = len(target) - lit
    if rem < 0 or rem > 4 * len(unk):
        return []
    # Literal-sequence per token: (is_unk, chars_or_None); for unknown slots we
    # walk with the precomputed lens, capturing the slice. No regex — this is
    # the hot path (180k compiles were the bottleneck).
    out = []
    for lens in _compositions(rem, len(unk)):
        if not all(lens):
            continue
        slots = []
        i = 0
        li = 0
        ok = True
        for k, t in tt:
            if k:
                slots.append((t, target[i:i + lens[li]]))
                i += lens[li]
                li += 1
            else:
                if target[i:i + len(t)] != t:
                    ok = False
                    break
                i += len(t)
        if ok and i == len(target):
            out.append(slots)
    return out


@lru_cache(maxsize=None)
def _solve_span_cached(span_toks, target):
    """Joint solve + rephrase-reorder variants. Unique slot assignments."""
    results = list(joint_match(span_toks, target))
    for tgi in [i for i, (k, _) in enumerate(span_toks) if k]:
        for nb in (tgi - 1, tgi + 1):
            if 0 <= nb < len(span_toks) and not span_toks[nb][0]:
                tt2 = list(span_toks)
                tt2[tgi], tt2[nb] = tt2[nb], tt2[tgi]
                results += joint_match(tuple(tt2), target)
    seen = set()
    out = []
    for s in results:
        key = tuple(sorted(s))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return tuple(out)


def solve_span(span_toks, target):
    """Joint solve + rephrase-reorder variants (memoized on hashable inputs)."""
    return _solve_span_cached(tuple(span_toks), target)


def derive(doc, corrections: dict[int, str], max_span_evidence: int = 200,
           max_pages: int | None = None) -> dict:
    results = {}
    if not corrections:
        return results
    cid_set = set(corrections)

    # Per-cid accumulators, char-precise slice solving.
    tgt_vals: dict = {c: {} for c in corrections}
    tgt_ex: dict = {c: {} for c in corrections}
    conflicts: dict = {c: {} for c in corrections}
    solved: dict = {c: 0 for c in corrections}
    totals: dict = {c: 0 for c in corrections}

    for pn, lines in all_lines(doc, max_pages):
        for line in lines:
            toks = tokens_of(line)
            present = {v for k, v in toks if k} & cid_set
            if not present:
                continue
            for cid in present:
                word = corrections[cid].strip()
                if not word:
                    continue
                totals[cid] += 1
                for value, span, slots in solve_line_tokens(
                        toks, cid, word, cap=max_span_evidence):
                    if not value:
                        continue
                    tgt_vals[cid][value] = tgt_vals[cid].get(value, 0) + 1
                    tgt_ex[cid].setdefault(value, []).append(f"p{pn} {span}")
                    solved[cid] += 1
                    for other, ov in slots:
                        if other != cid:
                            conflicts[cid].setdefault(other, {})
                            conflicts[cid][other][ov] = conflicts[cid][other].get(ov, 0) + 1

    for cid, word in corrections.items():
        word = word.strip()
        total = totals[cid]
        tv = tgt_vals[cid]
        if not word:
            results[str(cid)] = make_blank("no-windows")
            continue
        if not total:
            results[str(cid)] = make_blank("no-windows")
            continue
        if not tv:
            results[str(cid)] = {**make_blank("no-solution"), "windows_total": total}
            continue
        top = max(tv.values())
        uniq = [v for v, n in tv.items() if n == top]
        if len(uniq) == 1 and top >= 1:
            v = uniq[0]
            mode, mapping = ("ok", v)
            ev = tgt_ex[cid].get(v, [])[:3]
        elif len(tv) == 1 and top == 1 and total >= 2:
            v = next(iter(tv))
            mode, mapping = ("partial", v)
            ev = tgt_ex[cid].get(v, [])[:3]
        else:
            v, mode, mapping = None, "ambiguous", ""
            cands = sorted(tv, key=lambda k: -tv[k])
            ev = (tgt_ex[cid].get(cands[0], [])[:3] if cands else [])
        cands = sorted(tv, key=lambda k: -tv[k])
        results[str(cid)] = {
            "mapping": mapping, "mode": mode,
            "candidates": cands,
            "evidence": ev,
            "conflicts": {str(k): v for k, v in conflicts[cid].items()},
            "windows_total": total, "windows_solved": solved[cid],
        }
    return results


def make_blank(mode: str) -> dict:
    return {"mapping": "", "mode": mode, "candidates": [], "evidence": [],
            "conflicts": {}, "windows_total": 0, "windows_solved": 0}


def load_corrections(records) -> dict[int, str]:
    """Read legacy ``{cid, correct}`` and neutral review records.

    Neutral records are ``{key, value, undecodable, data}``; the CID comes from
    ``data.cid`` with ``key`` as a fallback. Blank and undecodable records are
    ignored.
    """
    out: dict[int, str] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if "cid" in record:
            cid = int(record["cid"])
            value = (record.get("correct") or "").strip()
            undecodable = bool(record.get("undecodable"))
        else:
            data = record.get("data") or {}
            raw_cid = data.get("cid", record.get("key"))
            if raw_cid is None:
                continue
            try:
                cid = int(raw_cid)
            except (TypeError, ValueError):
                continue
            value = (record.get("value") or record.get("correct") or "").strip()
            undecodable = bool(record.get("undecodable"))
        if value and not undecodable:
            out[cid] = value
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf")
    ap.add_argument("corrections")
    ap.add_argument("-o", "--output", default="output/cid_mappings.json")
    ap.add_argument("--max-pages", type=int, default=None)
    a = ap.parse_args(argv)

    from kagaj_core import pdf as core_pdf
    doc = core_pdf.open_pdf(a.pdf)
    with open(a.corrections, encoding="utf-8") as f:
        recs = json.load(f)
    corrections = load_corrections(recs)
    results = derive(doc, corrections, max_span_evidence=200, max_pages=a.max_pages)

    os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    flags = {"ok": "OK", "partial": "PARTIAL", "ambiguous": "AMBIG",
             "no-solution": "NONE", "no-windows": "NOWIN"}
    for cid, r in sorted(results.items(), key=lambda kv: int(kv[0])):
        print(f"  [{flags[r['mode']]}] cid={cid:<3} -> {r['mapping']!r} "
              f"cands={r['candidates']} sol={r['windows_solved']}/{r['windows_total']}")
    return 0 if all(r["mode"] in ("ok", "partial") for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())