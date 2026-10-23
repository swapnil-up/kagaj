"""Evidence-aware promotion of registry mappings into the canonical store.

Promotion is deliberately conservative. Registry evidence is required; a
shape-run value can confirm or contradict it but cannot promote a glyph alone.
The output is a candidate report, and only explicit ``--apply`` writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from kagaj_core.devanagari import validate

from .decode import census
from .embedded import EmbeddedFontCache
from .infer import aggregate_cids, infer_runs
from .mappings import get_value
from .registry import resolve_glyph

_STRONG_SOURCES = {"review"}


@dataclass(frozen=True)
class PromotionCandidate:
    font_id: str
    cid: int
    value: str
    score: float
    status: str
    support: int
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def promotable(self) -> bool:
        return not self.blockers

    def decision(self) -> dict:
        return {
            "key": f"{self.font_id}\u2571{self.cid}",
            "value": self.value,
            "undecodable": False,
            "inconsistent": False,
            "note": "promoted from glyph registry",
            "data": {
                "font": self.font_id,
                "font_id": self.font_id,
                "cid": self.cid,
                "source": "promote",
            },
        }

    def to_dict(self) -> dict:
        return {
            "font_id": self.font_id,
            "cid": self.cid,
            "value": self.value,
            "score": self.score,
            "status": self.status,
            "support": self.support,
            "promotable": self.promotable,
            "reasons": list(self.reasons),
            "blockers": list(self.blockers),
        }


def valid_value(value: str) -> bool:
    """Validate a CID value, allowing a leading mark on a virtual base."""
    if not value:
        return False
    if not validate(value):
        return True
    for prefix in ("\u0915", "\u0915\u094d"):
        if not validate(prefix + value):
            return True
    return False


def _review_source(entry: dict, font_id: str, cid: int) -> bool:
    return any(
        obs.get("source") in _STRONG_SOURCES
        and obs.get("font_id") == font_id
        and int(obs.get("cid") or -1) == cid
        for obs in entry.get("observations") or []
    )


def build_candidate(font_id: str, cid: int, bundle: dict | None, *,
                    inference=None, existing: str | None = None,
                    marked_undecodable: bool = False) -> PromotionCandidate | None:
    entry = bundle.get("entry") if bundle else None
    if entry is None and inference is None:
        return None

    reasons: list[str] = []
    blockers: list[str] = []
    if existing is not None:
        blockers.append(f"already mapped to {existing!r}")
    if marked_undecodable:
        blockers.append("marked undecodable")

    if entry is None:
        value = getattr(inference, "value", "") if inference else ""
        status = "none"
        support = 0
        blockers.append("no registry entry")
    else:
        status = entry.get("status") or "provisional"
        support = int(entry.get("support") or 0)
        value = entry.get("value") or ""
        if status == "conflict":
            blockers.append("registry conflict")
        elif not value:
            blockers.append("registry value is empty")
        elif support >= 2:
            reasons.append(f"registry confirmed by {support} documents")
        elif _review_source(entry, font_id, cid):
            reasons.append("reviewer-confirmed mapping")
        else:
            blockers.append("needs a second independent document")

    if inference is not None:
        inferred = getattr(inference, "value", "")
        if value and inferred and inferred != value:
            blockers.append(f"shape-run disagrees ({inferred})")
        elif entry is not None and value and inferred == value:
            reasons.append(f"shape-run agrees ({inferred})")

    if not valid_value(value):
        blockers.append("invalid Devanagari value")

    score = 0.5
    if entry is not None:
        score += 0.2 + min(support, 3) * 0.05
    if entry is not None and _review_source(entry, font_id, cid):
        score += 0.1
    if inference is not None and inference.value == value:
        score += 0.1
    if blockers:
        score -= 0.25
    score = round(max(0.0, min(score, 0.99)), 2)

    return PromotionCandidate(
        font_id=font_id,
        cid=cid,
        value=value,
        score=score,
        status=status,
        support=support,
        reasons=tuple(reasons),
        blockers=tuple(blockers),
    )


def build_candidates(census_result: dict, registry: dict, embedded,
                     store: dict, *, inferences=None,
                     cids: set[int] | None = None) -> list[PromotionCandidate]:
    by_cid = {
        (item.font_id, item.cid): item
        for item in (inferences or [])
    }
    out = []
    for font_id in sorted(census_result):
        for cid in sorted(census_result[font_id]):
            if cids is not None and cid not in cids:
                continue
            rec = census_result[font_id][cid]
            samples = rec.get("samples") or []
            sample = samples[0] if samples else {}
            xref = sample.get("font_xref")
            base_font = sample.get("base_font") or font_id
            bundle = (
                resolve_glyph(registry, embedded, xref, cid, base_font)
                if xref else None
            )
            existing = get_value(store, font_id, cid)
            marked = f"{font_id}\u2571{cid}" in store.get("undecodable", [])
            candidate = build_candidate(
                font_id, cid, bundle,
                inference=by_cid.get((font_id, cid)),
                existing=existing,
                marked_undecodable=marked,
            )
            if candidate is not None:
                out.append(candidate)
    return out


def promote_document(doc, store: dict, registry: dict, *,
                     reference_font: str | None = None, lexicon=None,
                     max_pages=None, cids: set[int] | None = None,
                     issues=None) -> list[PromotionCandidate]:
    census_result = census(doc, max_pages=max_pages, issues=issues)
    inferences = []
    if reference_font:
        runs = infer_runs(
            doc, reference_font=reference_font, lexicon=lexicon,
            max_pages=max_pages)
        inferences = aggregate_cids(runs)
    embedded = EmbeddedFontCache(doc)
    return build_candidates(
        census_result, registry, embedded, store,
        inferences=inferences, cids=cids)


def format_candidates(candidates) -> str:
    if not candidates:
        return "No promotion candidates."
    lines = [
        f"Promotable: {sum(1 for c in candidates if c.promotable)} "
        f"\u00b7 blocked: {sum(1 for c in candidates if not c.promotable)}",
    ]
    for candidate in sorted(
            candidates,
            key=lambda item: (not item.promotable, item.font_id, item.cid)):
        state = "PROMOTE" if candidate.promotable else "blocked"
        lines.append(
            f"[{state}] {candidate.font_id} cid={candidate.cid} "
            f"value={candidate.value!r} score={candidate.score:.2f} "
            f"status={candidate.status} support={candidate.support}")
        if candidate.reasons:
            lines.append("  reasons: " + "; ".join(candidate.reasons))
        if candidate.blockers:
            lines.append("  blockers: " + "; ".join(candidate.blockers))
    return "\n".join(lines)
