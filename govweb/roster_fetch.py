import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from . import paths


SOURCE_URL = (
    "https://oag.gov.np/api/front/local-level-report"
    "?province=&district=&municipality=&fiscal_year=&page=1&per_page=2000"
)
USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
ROSTER_PATH = paths.DATASET_DIR / "roster.json"
META_PATH = paths.DATASET_DIR / "roster_meta.json"


def clean_display(value):
    """Collapse whitespace without changing capitalization or wording."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def normalize_name(value):
    """Normalize whitespace and casing only."""
    return clean_display(value).casefold()


def first_present(mapping, keys):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def source_id(mapping, keys):
    value = first_present(mapping, keys)
    return "" if value is None else str(value)


def normalize_roster(payload):
    """Convert the OAG nested provinces hierarchy into flat records."""
    if not isinstance(payload, dict):
        raise ValueError("OAG response must be a JSON object")

    provinces = payload.get("provinces")
    if not isinstance(provinces, list):
        raise ValueError("OAG response must contain a provinces list")

    records = []
    province_ids = set()
    district_ids = set()

    for province in provinces:
        if not isinstance(province, dict):
            continue

        province_id = source_id(province, ("id", "province_id"))
        province_name = clean_display(
            first_present(province, ("name", "province_name", "title"))
        )
        if province_id:
            province_ids.add(province_id)

        districts = first_present(province, ("districts", "children")) or []
        if not isinstance(districts, list):
            continue

        for district in districts:
            if not isinstance(district, dict):
                continue

            district_id = source_id(district, ("id", "district_id"))
            district_name = clean_display(
                first_present(district, ("name", "district_name", "title"))
            )
            if district_id:
                district_ids.add(district_id)

            municipalities = first_present(
                district,
                ("municipalities", "local_levels", "local_levels_list", "children"),
            ) or []
            if not isinstance(municipalities, list):
                continue

            for municipality in municipalities:
                if not isinstance(municipality, dict):
                    continue

                municipality_id = source_id(
                    municipality,
                    ("id", "municipality_id", "local_level_id"),
                )
                name = clean_display(
                    first_present(
                        municipality,
                        ("name", "municipality_name", "local_level_name", "title"),
                    )
                )

                if not municipality_id or not name:
                    raise ValueError(
                        "Roster entry is missing a stable municipality ID or name"
                    )
                if not province_id or not province_name:
                    raise ValueError("Roster entry has missing province information")
                if not district_id or not district_name:
                    raise ValueError("Roster entry has missing district information")

                records.append(
                    {
                        "province_id": province_id,
                        "province": province_name,
                        "district_id": district_id,
                        "district": district_name,
                        "municipality_id": municipality_id,
                        "name": name,
                        "normalized_name": normalize_name(name),
                    }
                )

    if not records:
        raise ValueError("OAG provinces hierarchy produced no municipality records")

    return records, len(province_ids), len(district_ids)


def fetch_payload():
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"OAG API returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def main():
    try:
        payload = fetch_payload()
        records, province_count, district_count = normalize_roster(payload)

        fetched_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "source_url": SOURCE_URL,
            "fetched_at": fetched_at,
            "province_count": province_count,
            "district_count": district_count,
            "municipality_count": len(records),
            "record_count": len(records),
            "normalization": (
                "Display names: surrounding and repeated whitespace collapsed; "
                "original capitalization retained. normalized_name: whitespace "
                "collapsed and Unicode case-folded. No other substitutions."
            ),
        }

        ROSTER_PATH.parent.mkdir(parents=True, exist_ok=True)
        META_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Replace files atomically so interrupted writes do not corrupt existing data.
        for destination, content in (
            (ROSTER_PATH, records),
            (META_PATH, metadata),
        ):
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(
                json.dumps(content, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)

        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Roster fetch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
