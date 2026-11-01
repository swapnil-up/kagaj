"""Resolve garbled chart legend labels to canonical offense names."""

from __future__ import annotations

from .schema import OFFENSES, match_offense

HEINOUS_ORDER = ["murder", "trafficking", "rape", "kidnapping"]
SERIOUS_FULL_ORDER = [
    "attempted_murder",
    "suicide_abetment",
    "abortion",
    "dacoity",
    "burglary",
    "assault",
]
SERIOUS_MODERN_ORDER = [
    "attempted_murder",
    "suicide_abetment",
    "dacoity",
    "burglary",
    "assault",
]

HEINOUS = set(HEINOUS_ORDER)
SERIOUS = set(SERIOUS_FULL_ORDER)


def chart_kind(canonical: list[str | None]) -> str | None:
    present = {c for c in canonical if c}
    if present & SERIOUS:
        return "serious"
    if present & HEINOUS:
        return "heinous"
    return None


def title_kind(title: str) -> str | None:
    label = title
    if any(k in label for k in ("जघन्य", "ज न्य", "जघन्द्र", "जघन्र", "जघन", "ज न्य")):
        return "heinous"
    if any(k in label for k in ("गम्भीर", "गम्िीर", "गम्िर", "गम्भीर")):
        return "serious"
    return None


def resolve_series(
    raw_labels: list[str], title: str = ""
) -> tuple[list[str | None], str | None, list[str]]:
    """Return (canonical, kind, warnings)."""
    warnings: list[str] = []
    matched = [match_offense(label) if label else None for label in raw_labels]
    kind = title_kind(title) or chart_kind(matched)

    prior: list[str] | None = None
    if kind == "heinous":
        prior = HEINOUS_ORDER
    elif kind == "serious":
        if len(raw_labels) >= 6:
            prior = SERIOUS_FULL_ORDER
        else:
            prior = SERIOUS_MODERN_ORDER

    resolved = list(matched)
    if prior and len(prior) == len(resolved):
        if any(c is None for c in resolved):
            for i, canon in enumerate(prior):
                if resolved[i] is None:
                    resolved[i] = canon
                    warnings.append(f"series {i} label missing; inferred {canon} from chart order")
    elif prior and len(prior) != len(resolved):
        warnings.append(
            f"series count {len(resolved)} does not match known {kind} order ({len(prior)})"
        )

    if any(c is None for c in resolved):
        warnings.append("unresolved series: " + ", ".join(repr(r) for r, c in zip(raw_labels, resolved) if c is None))

    seen: dict[str, int] = {}
    for i, canon in enumerate(resolved):
        if canon is None:
            continue
        if canon in seen:
            warnings.append(f"duplicate canonical offense {canon} at series {seen[canon]} and {i}")
        else:
            seen[canon] = i
    return resolved, kind, warnings


def offense_nepali(canonical: str) -> str:
    return OFFENSES[canonical][1]
