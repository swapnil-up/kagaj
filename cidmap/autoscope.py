"""Bootstrap font-scoped mappings from exact reference-font outlines.

The embedded subsets have no usable cmap, but an exact outline match against
the original font is strong evidence for a single glyph. Unambiguous matches
become store mappings; ambiguous shapes stay for human review unless optional
lexicon context resolves the glyph's role. It never overwrites a differing
fallback silently.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from .confidence import valid_value
from .mappings import get_value, set_value
from .probe import probe_document

DEFAULT_MAX_SCORE = 0.75
DEFAULT_MIN_MARGIN = 1.0


@dataclass(frozen=True)
class ScopedMapping:
    font_id: str
    cid: int
    value: str
    score: float
    glyph: str
    pages: tuple[int, ...] = ()
    exact: bool = False
    fallback: str | None = None
    lexicon: str | None = None

    @property
    def tier(self) -> str:
        return "exact" if self.exact else "near"

    def to_dict(self) -> dict:
        return {
            "font_id": self.font_id,
            "cid": self.cid,
            "value": self.value,
            "score": self.score,
            "glyph": self.glyph,
            "match": self.tier,
            "fallback": self.fallback,
            "lexicon": self.lexicon,
            "pages": list(self.pages),
        }


@dataclass
class RejectedMapping:
    font_id: str
    cid: int
    value: str
    score: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "font_id": self.font_id,
            "cid": self.cid,
            "value": self.value,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass
class ScopePlan:
    pdf: str
    mappings: list[ScopedMapping] = field(default_factory=list)
    rejected: list[RejectedMapping] = field(default_factory=list)
    max_pages: int | None = None
    reference: dict = field(default_factory=dict)
    lexicon_votes: int = 0

    @property
    def fonts(self) -> int:
        return len({item.font_id for item in self.mappings})

    def to_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "max_pages": self.max_pages,
            "mappings": len(self.mappings),
            "fonts": self.fonts,
            "reference": self.reference,
            "lexicon_votes": self.lexicon_votes,
            "items": [item.to_dict() for item in self.mappings],
            "rejected": [item.to_dict() for item in self.rejected],
        }


def _candidate_values(candidates) -> list[tuple[str, float, str, bool]]:
    values = {}
    for candidate in candidates or []:
        glyph = str(candidate.get("glyph") or "")
        if not glyph or glyph.startswith(".") or "notdef" in glyph.lower():
            continue
        value = str(candidate.get("value") or "")
        if not value:
            continue
        score = float(candidate.get("score") or 0.0)
        exact = bool(candidate.get("exact", score == 0.0))
        current = values.get(value)
        if current is None or score < current[0]:
            values[value] = (score, glyph, exact)
    return sorted(
        ((value, score, glyph, exact)
         for value, (score, glyph, exact) in values.items()),
        key=lambda item: (item[1], item[0]),
    )


def _lexical_cids(result):
    """CIDs where lexicon context can change an autoscope decision."""
    cids = set()
    for font in result.get("fonts", []):
        candidates = font.get("candidates") or {}
        for row in font.get("unknown_cids", []):
            cid = int(row.get("cid") or 0)
            values = _candidate_values(candidates.get(str(cid)))
            if not values:
                continue
            exact = values[0][3]
            second_exact = values[1][3] if len(values) > 1 else False
            if exact and second_exact:
                cids.add(cid)
            elif not exact and len(values) > 1:
                cids.add(cid)
    return cids


def _lexical_values(doc, reference_font: str, max_pages, lexicon, cids=None):
    """Return ``(font_id, cid) -> CidInference`` from shape-run inference.

    Lexicon evidence is optional. Missing ``uharfbuzz`` or an empty lexicon
    leaves near-tier matching shape-only instead of failing autoscope.
    """
    if lexicon is False or not reference_font:
        return {}
    if not Path(reference_font).is_file():
        return {}
    try:
        from .infer import aggregate_cids, infer_runs
        from .lexicon import NepaliLexicon

        if lexicon is None:
            lex = NepaliLexicon.load()
            if not len(lex):
                return {}
        else:
            lex = lexicon
        runs = infer_runs(
            doc, reference_font=reference_font, lexicon=lex,
            max_pages=max_pages, cids=cids)
        best = [
            type(run)(
                page=run.page,
                font_id=run.font_id,
                font_xref=run.font_xref,
                observed=run.observed,
                candidates=run.candidates[:1],
            )
            for run in runs
        ]
        return {
            (item.font_id, item.cid): item
            for item in aggregate_cids(best)
        }
    except Exception as exc:
        warnings.warn(f"autoscope: lexicon evidence unavailable ({exc})",
                      RuntimeWarning, stacklevel=3)
        return {}


def build_scope_plan(doc, store: dict, *, reference_font: str | None = None,
                     reference_fonts=None,
                     max_pages=None, max_score: float = DEFAULT_MAX_SCORE,
                     min_margin: float = DEFAULT_MIN_MARGIN,
                     lexicon=False) -> ScopePlan:
    if not reference_fonts and not reference_font:
        raise ValueError("reference_font or reference_fonts is required")
    if reference_fonts:
        from .reference_fonts import resolve_reference_fonts

        resolved = []
        for value in reference_fonts:
            resolved.extend(str(path) for path in resolve_reference_fonts(value))
        reference_fonts = resolved
        reference_font = reference_fonts[0]
    result = probe_document(
        doc, max_pages=max_pages, reference_font=reference_font,
        reference_fonts=reference_fonts)
    lexical = _lexical_values(
        doc, reference_font, max_pages, lexicon,
        cids=_lexical_cids(result) if lexicon is not False else None)
    plan = ScopePlan(
        pdf=result.get("pdf") or "",
        max_pages=result.get("pages_scanned"),
        reference=result.get("reference") or {},
        lexicon_votes=len(lexical),
    )
    for font in result.get("fonts", []):
        font_id = font.get("font_id") or ""
        if not font_id:
            continue
        for row in font.get("unknown_cids", []):
            cid = int(row.get("cid") or 0)
            values = _candidate_values(
                (font.get("candidates") or {}).get(str(cid)))
            if not values:
                continue
            value, score, glyph, exact = values[0]
            second = values[1][1] if len(values) > 1 else None
            second_exact = values[1][3] if len(values) > 1 else False
            inferred = lexical.get((font_id, cid))
            lexical_value = inferred.value if inferred is not None else None
            if not valid_value(value):
                plan.rejected.append(RejectedMapping(
                    font_id, cid, value, score, "invalid value"))
                continue
            if exact:
                if second_exact:
                    exact_values = [item for item in values if item[3]]
                    chosen = [item for item in exact_values
                              if item[0] == lexical_value]
                    if len(chosen) == 1:
                        value, score, glyph, exact = chosen[0]
                    else:
                        glyphs = {item[2] for item in exact_values}
                        inferred_exact = (
                            inferred is not None
                            and inferred.shape_score == 0.0
                            and lexical_value
                        )
                        if (inferred_exact and len(glyphs) == 1
                                and valid_value(lexical_value)):
                            value = lexical_value
                            score = 0.0
                            glyph = glyphs.pop()
                            exact = True
                        else:
                            plan.rejected.append(RejectedMapping(
                                font_id, cid, value, score,
                                "ambiguous exact outline match"))
                            continue
            else:
                if score > max_score:
                    plan.rejected.append(RejectedMapping(
                        font_id, cid, value, score,
                        "outline score too high"))
                    continue
                if second is not None and second - score < min_margin:
                    plan.rejected.append(RejectedMapping(
                        font_id, cid, value, score,
                        "ambiguous outline match"))
                    continue
                if lexical_value is not None and lexical_value != value:
                    plan.rejected.append(RejectedMapping(
                        font_id, cid, value, score,
                        f"lexicon disagrees ({lexical_value})"))
                    continue
            scoped = store.get("fonts", {}).get(font_id, {}).get(cid)
            if scoped is not None:
                continue
            existing = get_value(store, font_id, cid)
            if existing is not None and existing != value and not exact:
                plan.rejected.append(RejectedMapping(
                    font_id, cid, value, score,
                    f"fallback already maps to {existing!r}"))
                continue
            plan.mappings.append(ScopedMapping(
                font_id=font_id,
                cid=cid,
                value=value,
                score=score,
                glyph=glyph,
                pages=tuple(row.get("pages") or ()),
                exact=exact,
                fallback=existing if existing != value else None,
                lexicon=lexical_value if lexical_value == value else None,
            ))
    return plan


def apply_scope_plan(store: dict, plan: ScopePlan) -> int:
    for item in plan.mappings:
        evidence = [f"ref:{item.glyph}", f"score:{item.score:.3f}"]
        if item.pages:
            evidence.insert(0, f"p{item.pages[0]}")
        meta = {
            "source": "reference",
            "match": item.tier,
            "evidence": evidence[:3],
        }
        if item.fallback is not None:
            meta["fallback_overridden"] = item.fallback
        if item.lexicon is not None:
            meta["lexicon"] = item.lexicon
        set_value(store, item.font_id, item.cid, item.value, meta)
    return len(plan.mappings)


def rejected_jsonl(plan: ScopePlan) -> str:
    return "\n".join(
        json.dumps({"pdf": plan.pdf, **item.to_dict()}, ensure_ascii=False)
        for item in plan.rejected
    ) + ("\n" if plan.rejected else "")


def format_plan(plan: ScopePlan, *, limit: int = 20) -> str:
    exact = sum(1 for item in plan.mappings if item.exact)
    near = len(plan.mappings) - exact
    lines = [
        f"PDF: {plan.pdf or '(unknown)'}",
        f"Reference matches: {len(plan.mappings)} across "
        f"{plan.fonts} font(s) (exact={exact}, near={near}, "
        f"lexicon_votes={plan.lexicon_votes}) \u00b7 "
        f"rejected: {len(plan.rejected)}",
    ]
    if plan.reference:
        lines.append(
            f"Reference: {plan.reference.get('family') or '?'} "
            f"{plan.reference.get('style') or ''} "
            f"{plan.reference.get('version') or '?'} "
            f"created={plan.reference.get('created') or '?'} "
            f"sha={plan.reference.get('sha256', '')[:12]}")
    for item in plan.mappings[:limit]:
        pages = f" p{item.pages[0]}" if item.pages else ""
        override = (f" overrides fallback {item.fallback!r}"
                    if item.fallback is not None else "")
        lexical = f" lexicon={item.lexicon!r}" if item.lexicon else ""
        lines.append(
            f"  [{item.tier}] {item.font_id} cid={item.cid} -> "
            f"{item.value!r} ({item.glyph}, {item.score:.3f})"
            f"{pages}{override}{lexical}")
    if len(plan.mappings) > limit:
        lines.append(f"  \u2026 {len(plan.mappings) - limit} more")
    if not plan.mappings:
        lines.append("No new mappings.")
    return "\n".join(lines)
