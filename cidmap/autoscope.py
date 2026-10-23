"""Bootstrap font-scoped mappings from exact reference-font outlines.

The embedded subsets have no usable cmap, but an exact outline match against
the original font is strong evidence for a single glyph. This command turns
only unambiguous matches into store mappings; ambiguous shapes stay for human
review. It never overwrites a differing fallback silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

    def to_dict(self) -> dict:
        return {
            "font_id": self.font_id,
            "cid": self.cid,
            "value": self.value,
            "score": self.score,
            "glyph": self.glyph,
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

    @property
    def fonts(self) -> int:
        return len({item.font_id for item in self.mappings})

    def to_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "max_pages": self.max_pages,
            "mappings": len(self.mappings),
            "fonts": self.fonts,
            "items": [item.to_dict() for item in self.mappings],
            "rejected": [item.to_dict() for item in self.rejected],
        }


def _candidate_values(candidates) -> list[tuple[str, float, str]]:
    values = {}
    for candidate in candidates or []:
        glyph = str(candidate.get("glyph") or "")
        if not glyph or glyph.startswith(".") or "notdef" in glyph.lower():
            continue
        value = str(candidate.get("value") or "")
        if not value:
            continue
        score = float(candidate.get("score") or 0.0)
        current = values.get(value)
        if current is None or score < current[0]:
            values[value] = (score, glyph)
    return sorted(
        ((value, score, glyph) for value, (score, glyph) in values.items()),
        key=lambda item: (item[1], item[0]),
    )


def build_scope_plan(doc, store: dict, *, reference_font: str,
                     max_pages=None, max_score: float = DEFAULT_MAX_SCORE,
                     min_margin: float = DEFAULT_MIN_MARGIN) -> ScopePlan:
    result = probe_document(
        doc, max_pages=max_pages, reference_font=reference_font)
    plan = ScopePlan(
        pdf=result.get("pdf") or "",
        max_pages=result.get("pages_scanned"),
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
            value, score, glyph = values[0]
            second = values[1][1] if len(values) > 1 else None
            if not valid_value(value):
                plan.rejected.append(RejectedMapping(
                    font_id, cid, value, score, "invalid value"))
                continue
            if score > max_score:
                plan.rejected.append(RejectedMapping(
                    font_id, cid, value, score, "outline score too high"))
                continue
            if second is not None and second - score < min_margin:
                plan.rejected.append(RejectedMapping(
                    font_id, cid, value, score, "ambiguous outline match"))
                continue
            scoped = store.get("fonts", {}).get(font_id, {}).get(cid)
            if scoped is not None:
                continue
            existing = get_value(store, font_id, cid)
            if existing is not None and existing != value:
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
            ))
    return plan


def apply_scope_plan(store: dict, plan: ScopePlan) -> int:
    for item in plan.mappings:
        evidence = [f"ref:{item.glyph}", f"score:{item.score:.3f}"]
        if item.pages:
            evidence.insert(0, f"p{item.pages[0]}")
        set_value(store, item.font_id, item.cid, item.value, {
            "source": "reference",
            "evidence": evidence[:3],
        })
    return len(plan.mappings)


def format_plan(plan: ScopePlan, *, limit: int = 20) -> str:
    lines = [
        f"PDF: {plan.pdf or '(unknown)'}",
        f"Exact reference matches: {len(plan.mappings)} across "
        f"{plan.fonts} font(s) \u00b7 rejected: {len(plan.rejected)}",
    ]
    for item in plan.mappings[:limit]:
        pages = f" p{item.pages[0]}" if item.pages else ""
        lines.append(
            f"  {item.font_id} cid={item.cid} -> {item.value!r} "
            f"({item.glyph}, {item.score:.3f}){pages}")
    if len(plan.mappings) > limit:
        lines.append(f"  \u2026 {len(plan.mappings) - limit} more")
    if not plan.mappings:
        lines.append("No new mappings.")
    return "\n".join(lines)
