import json
from pathlib import Path

from . import paths

DEFAULT_ROSTER_PATH = paths.DATASET_DIR / "roster.json"


def normalize_name(value):
    """Collapse whitespace and case-fold a name without semantic rewriting."""
    return " ".join(str(value).split()).casefold()


def load_roster(path=DEFAULT_ROSTER_PATH):
    """Load and validate a normalized roster JSON file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        records = json.load(handle)

    if not isinstance(records, list):
        raise ValueError("Roster must be a JSON array")

    required = {
        "province_id",
        "province",
        "district_id",
        "district",
        "municipality_id",
        "name",
        "normalized_name",
    }
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not required.issubset(record):
            raise ValueError(f"Invalid roster record at index {index}")
    return records


def all_local_levels(roster):
    """Return every local-level record."""
    return list(roster)


def by_district(roster, district):
    """Query by district display name or stable district ID."""
    target = str(district)
    return [
        record
        for record in roster
        if record["district_id"] == target
        or normalize_name(record["district"]) == normalize_name(target)
    ]


def by_province(roster, province):
    """Query by province display name or stable province ID."""
    target = str(province)
    return [
        record
        for record in roster
        if record["province_id"] == target
        or normalize_name(record["province"]) == normalize_name(target)
    ]


def counts(roster):
    """Return actual province, district, and local-level counts."""
    return {
        "province_count": len({record["province_id"] for record in roster}),
        "district_count": len({record["district_id"] for record in roster}),
        "municipality_count": len(roster),
    }


def find_local_level(roster, name):
    """Find local-level records by normalized name; may return multiple matches."""
    target = normalize_name(name)
    return [record for record in roster if record["normalized_name"] == target]
