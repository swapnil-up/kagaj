"""Infer unknown CID values from shaped word runs and a Nepali lexicon."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from kagaj_core.devanagari import validate

from .decode import glyphs as extract_glyphs, is_unknown
from .embedded import EmbeddedFontCache
from .fonts import FontResolutionError
from .lexicon import LexiconIndex, NepaliLexicon
from .reference import shape_distance
from .runs import runs_with_unknown, word_runs
from .shaping import ReferenceShaper


@dataclass(frozen=True)
class GlyphAssignment:
    index: int
    cid: int
    value: str
    score: float


@dataclass(frozen=True)
class RunCandidate:
    word: str
    score: float
    alignment: tuple[tuple[int, int], ...]
    assignments: tuple[GlyphAssignment, ...]


@dataclass(frozen=True)
class RunInference:
    page: int
    font_id: str
    font_xref: int | None
    observed: str
    candidates: tuple[RunCandidate, ...]


@dataclass(frozen=True)
class CidInference:
    font_id: str
    cid: int
    value: str
    score: float
    runs: int


_NO_MATCH = 120.0
_GAP = 50.0
_CLASS_PENALTY = 40.0


def _observed_text(run):
    return "".join(
        f"\u27e6{g['cid']}\u27e7" if is_unknown(g.get("c") or "")
        else (g.get("c") or "")
        for g in run.glyphs
    )


def _known_compatible(char, word):
    return not char or char in word


def _candidate_value(shaper, word, candidate):
    value = shaper.value_for(word, candidate)
    if value:
        return value
    span = shaper.cluster_span(word, candidate.cluster)
    return span if len(span) == 1 else None


def _align(observed, candidate_glyphs, shaper, word):
    n, m = len(observed), len(candidate_glyphs)
    inf = 1e18
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == inf:
                continue
            if i < n and j < m:
                obs = observed[i]
                cand = candidate_glyphs[j]
                distance = shape_distance(obs["shape"], cand.shape)
                if distance >= 1e6:
                    distance = _NO_MATCH
                if not is_unknown(obs["char"]):
                    value = _candidate_value(shaper, word, cand)
                    if not _known_compatible(obs["char"], value or ""):
                        distance += _CLASS_PENALTY
                cost = dp[i][j] + distance
                if cost < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = cost
                    back[i + 1][j + 1] = ("match", i, j)
            if i < n and dp[i][j] + _GAP < dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j] + _GAP
                back[i + 1][j] = ("skip_observed", i, j)
            if j < m and dp[i][j] + _GAP < dp[i][j + 1]:
                dp[i][j + 1] = dp[i][j] + _GAP
                back[i][j + 1] = ("skip_candidate", i, j)
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        kind, pi, pj = step
        if kind == "match":
            pairs.append((pi, pj))
        i, j = pi, pj
    pairs.reverse()
    return dp[n][m], tuple(pairs)


def infer_runs(doc, *, reference_font, lexicon=None, max_pages=None,
               max_candidates=5, max_word_candidates=2000,
               max_dp_candidates=200) -> list[RunInference]:
    shaper = ReferenceShaper.from_path(reference_font)
    if isinstance(lexicon, (str, bytes)) or hasattr(lexicon, "__fspath__"):
        lexicon = NepaliLexicon.load(lexicon)
    lexicon = lexicon or NepaliLexicon.load()
    index = LexiconIndex(lexicon, shaper)
    embedded = EmbeddedFontCache(doc)
    pages = range(len(doc)) if max_pages is None else range(
        min(max_pages, len(doc)))
    out = []
    for pn in pages:
        page = doc[pn]
        try:
            page_glyphs = extract_glyphs(page, dedup=True)
        except FontResolutionError:
            continue
        for run in runs_with_unknown(word_runs(page_glyphs, page=pn + 1)):
            if len(run.glyphs) < 2:
                continue
            candidates = _infer_run(
                run, shaper, index, lexicon, embedded,
                max_candidates=max_candidates,
                max_word_candidates=max_word_candidates,
                max_dp_candidates=max_dp_candidates,
            )
            if candidates:
                out.append(RunInference(
                    page=run.page,
                    font_id=run.font_id,
                    font_xref=run.font_xref,
                    observed=_observed_text(run),
                    candidates=tuple(candidates),
                ))
    return out


def _align_direct(observed, candidate_glyphs, shaper, word):
    total = 0.0
    pairs = []
    for index, (obs, cand) in enumerate(zip(observed, candidate_glyphs)):
        distance = shape_distance(obs["shape"], cand.shape)
        if distance >= 1e6:
            distance = _NO_MATCH
        if not is_unknown(obs["char"]):
            value = _candidate_value(shaper, word, cand)
            if not _known_compatible(obs["char"], value or ""):
                distance += _CLASS_PENALTY
        total += distance
        pairs.append((index, index))
    return total, tuple(pairs)


def _infer_run(run, shaper, index, lexicon, embedded, *, max_candidates,
               max_word_candidates, max_dp_candidates=200):
    observed = []
    for glyph in run.glyphs:
        cid = glyph.get("cid")
        observed.append({
            "cid": cid,
            "char": glyph.get("c") or "",
            "shape": embedded.shape(run.font_xref, cid)
            if run.font_xref is not None else None,
        })
    known_chars = Counter(
        item["char"] for item in observed if not is_unknown(item["char"])
    )
    pool = index.candidates_by_length(len(run.glyphs))
    if known_chars:
        pool = [
            entry for entry in pool
            if all(entry[0].count(char) >= count
                   for char, count in known_chars.items())
        ]
    fast = []
    for word, shaped in pool[:max_word_candidates]:
        cost, _ = _align_direct(observed, shaped, shaper, word)
        fast.append((cost, word, shaped))
    fast.sort(key=lambda item: (item[0], item[1]))
    ranked = []
    for _, word, shaped in fast[:max_dp_candidates]:
        cost, pairs = _align(observed, shaped, shaper, word)
        assignments = []
        for i, j in pairs:
            if not is_unknown(observed[i]["char"]):
                continue
            value = _candidate_value(shaper, word, shaped[j])
            if not value:
                continue
            assignments.append(GlyphAssignment(
                index=i,
                cid=observed[i]["cid"],
                value=value,
                score=shape_distance(observed[i]["shape"], shaped[j].shape),
            ))
        if not assignments:
            continue
        score = cost
        if word in lexicon:
            score -= 60.0
        if not validate(word):
            score -= 20.0
        ranked.append((score, word, pairs, tuple(assignments)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [
        RunCandidate(word=word, score=score, alignment=pairs,
                     assignments=assignments)
        for score, word, pairs, assignments in ranked[:max_candidates]
    ]


def aggregate_cids(inferences) -> list[CidInference]:
    votes = defaultdict(lambda: defaultdict(lambda: [0, 0.0, set()]))
    for inference in inferences:
        for candidate in inference.candidates:
            for assignment in candidate.assignments:
                key = (inference.font_id, assignment.cid)
                bucket = votes[key][assignment.value]
                bucket[0] += 1
                bucket[1] += candidate.score
                bucket[2].add(inference.page)
    out = []
    for (font_id, cid), values in votes.items():
        value, (count, total, pages) = min(
            values.items(), key=lambda item: (item[1][1], -item[1][0]))
        out.append(CidInference(
            font_id=font_id,
            cid=cid,
            value=value,
            score=total / max(count, 1),
            runs=len(pages),
        ))
    out.sort(key=lambda item: (item.font_id, item.cid))
    return out


def format_inference(inferences) -> str:
    lines = []
    for inference in inferences:
        lines.append(
            f"p{inference.page}  {inference.font_id}  {inference.observed}"
        )
        for candidate in inference.candidates:
            values = " ".join(
                f"CID {assignment.cid}={assignment.value}"
                for assignment in candidate.assignments
            )
            lines.append(
                f"  {candidate.score:8.2f}  {candidate.word}"
                + (f"  [{values}]" if values else "")
            )
    if not lines:
        return "No shape-run candidates."
    return "\n".join(lines)


def inference_payload(inferences, cids=None) -> dict:
    runs = []
    for inference in inferences:
        candidates = []
        for candidate in inference.candidates:
            assignments = [
                {
                    "index": assignment.index,
                    "cid": assignment.cid,
                    "value": assignment.value,
                    "score": assignment.score,
                }
                for assignment in candidate.assignments
                if cids is None or assignment.cid in cids
            ]
            if not assignments:
                continue
            candidates.append({
                "word": candidate.word,
                "score": candidate.score,
                "alignment": [list(pair) for pair in candidate.alignment],
                "assignments": assignments,
            })
        if candidates:
            runs.append({
                "page": inference.page,
                "font_id": inference.font_id,
                "font_xref": inference.font_xref,
                "observed": inference.observed,
                "candidates": candidates,
            })
    cid_rows = [
        {
            "font_id": item.font_id,
            "cid": item.cid,
            "value": item.value,
            "score": item.score,
            "runs": item.runs,
        }
        for item in aggregate_cids(inferences)
        if cids is None or item.cid in cids
    ]
    return {"runs": runs, "cids": cid_rows}
