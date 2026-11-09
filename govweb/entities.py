"""Classify every discovered apex hostname into an owning public body.

The unit of the dataset is a hostname, and only local levels have an
evidence-bearing attribution. This module widens the lens to the whole observed
``.gov.np`` universe by assigning each apex an owner *type* and scope from the
same kinds of committed sources the attribution engine uses.

It never guesses an owner from a name. A hostname is classified only when a
committed source names an organization and that organization's website agrees
with the hostname; everything else stays ``unknown`` and is counted. The
residual is the queue for the Phase 2 root-title and certificate-subject
collection, not a hole to be filled by inference.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import paths

SEED_FILE = paths.SOURCE_DIR / "owner_seed.json"

OWNER_TYPES = (
    "local_level",
    "province",
    "ministry",
    "department_or_office",
    "court",
    "commission",
    "security_force",
    "university_or_school",
    "hospital_or_health",
    "corporation_or_authority",
    "park_or_heritage",
    "media_or_culture",
    "other_government",
    "unknown",
)

OWNER_SCOPES = {
    "local_level": "local",
    "province": "provincial",
    "ministry": "central",
    "department_or_office": "central",
    "court": "central",
    "commission": "central",
    "security_force": "central",
    "university_or_school": "central",
    "hospital_or_health": "central",
    "corporation_or_authority": "central",
    "park_or_heritage": "central",
    "media_or_culture": "central",
    "other_government": "central",
    "unknown": "unknown",
}

# Ordered most specific first; the first phrase that matches wins.
_TYPE_RULES = (
    ("province", ("province of nepal", "province", "pradesh")),
    ("ministry", ("ministry", "mantralaya")),
    ("court", ("court", "supreme court", "judicial")),
    ("commission", ("commission", "authority", "constitutional body", "ombudsman")),
    ("security_force", ("police", "army", "armed police", "military", "security force")),
    ("university_or_school", ("university", "college", "campus", "school", "academy", "institute")),
    ("hospital_or_health", ("hospital", "medical", "health", "blood bank")),
    ("park_or_heritage", ("national park", "wildlife reserve", "conservation area", "heritage", "museum")),
    ("media_or_culture", ("radio", "broadcasting", "television", "news agency", "library", "culture")),
    ("corporation_or_authority", ("corporation", "board", "company", "enterprise", "bank", "development bank")),
    ("department_or_office", ("department", "office", "bureau", "directorate", "council", "committee", "center", "centre")),
    ("local_level", ("municipality", "rural municipality", "metropolitan city", "sub-metropolitan", "gaunpalika", "nagarpalika", "village development committee", "city")),
)

_NEPAL_QUALIFIER = re.compile(r"\b(nepal|nepali|nepalese|of nepal)\b", re.IGNORECASE)


def _load(relative: str | Path) -> object | None:
    path = paths.DATASET_DIR / relative if isinstance(relative, str) else relative
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _hostname(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value if "//" in value else f"//{value}")
    return (parsed.hostname or "").lower().rstrip(".")


def classify_description(description: str | None) -> tuple[str, str]:
    """Map a source description to an owner type and scope.

    Returns ``("unknown", "unknown")`` when the text carries no government
    signal, so a description like "football club" is never forced into a type.
    """
    text = (description or "").lower()
    if not text:
        return "unknown", "unknown"
    for owner_type, phrases in _TYPE_RULES:
        if any(phrase in text for phrase in phrases):
            return owner_type, OWNER_SCOPES[owner_type]
    if _NEPAL_QUALIFIER.search(text) or "government" in text or "govt" in text:
        return "other_government", "central"
    return "unknown", "unknown"


def load_wikidata_by_host() -> dict[str, list[dict]]:
    document = _load("sources/wikidata_nepal_websites.json")
    items = document.get("items", []) if isinstance(document, dict) else []
    by_host: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        host = _hostname(item.get("website"))
        if host:
            by_host[host].append(item)
    return by_host


def load_seed() -> dict[str, dict]:
    document = _load(SEED_FILE)
    entries = document.get("owners", []) if isinstance(document, dict) else []
    seed: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        host = _hostname(entry.get("hostname"))
        if host:
            seed[host] = entry
    return seed


def _attribution_index() -> dict[str, dict]:
    document = _load("attribution.json") or {}
    records = document.get("records", []) if isinstance(document, dict) else []
    index: dict[str, dict] = {}
    for record in records:
        host = str(record.get("hostname") or "").lower().rstrip(".")
        if host:
            index[host] = record
    return index


def apex_of(hostname: str) -> str:
    labels = hostname.strip(".").lower().split(".")
    return ".".join(labels[-3:]) if len(labels) > 3 else ".".join(labels)


def classify(
    hostnames: list[str],
    *,
    attribution: dict[str, dict] | None = None,
    wikidata_by_host: dict[str, list[dict]] | None = None,
    seed: dict[str, dict] | None = None,
    generated_at: str | None = None,
) -> dict:
    attribution = attribution if attribution is not None else _attribution_index()
    wikidata_by_host = wikidata_by_host if wikidata_by_host is not None else load_wikidata_by_host()
    seed = seed if seed is not None else load_seed()

    apexes = sorted({apex_of(host) for host in hostnames if host})
    records: list[dict] = []
    for apex in apexes:
        records.append(
            classify_apex(apex, attribution=attribution, wikidata_by_host=wikidata_by_host, seed=seed)
        )

    by_type = Counter(record["owner_type"] for record in records)
    stamp = generated_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "report_type": "govweb_entities",
        "generated_at": stamp,
        "apex_hostnames": len(apexes),
        "classified": sum(1 for record in records if record["owner_type"] != "unknown"),
        "unclassified": by_type.get("unknown", 0),
        "by_type": dict(sorted(by_type.items())),
        "methods": dict(sorted(Counter(record["method"] for record in records).items())),
        "records": records,
    }


def classify_apex(
    apex: str,
    *,
    attribution: dict[str, dict],
    wikidata_by_host: dict[str, list[dict]],
    seed: dict[str, dict],
) -> dict:
    local = attribution.get(apex)
    if local:
        return {
            "apex_hostname": apex,
            "owner_label": local.get("local_level_name", ""),
            "owner_type": "local_level",
            "owner_scope": "local",
            "method": f"attribution:{local.get('method', '')}".rstrip(":"),
            "confidence": local.get("confidence", "medium"),
            "qid": "",
            "district": local.get("district", ""),
            "local_level_id": str(local.get("local_level_id", "")),
            "evidence_url": local.get("evidence_url", ""),
            "evidence_note": (
                f"Local level '{local.get('local_level_name')}' in {local.get('district')}; "
                f"inherited from the hostname attribution."
            ),
        }

    override = seed.get(apex)
    if override:
        owner_type = str(override.get("owner_type") or "other_government")
        return {
            "apex_hostname": apex,
            "owner_label": str(override.get("owner_label") or ""),
            "owner_type": owner_type if owner_type in OWNER_TYPES else "other_government",
            "owner_scope": str(override.get("owner_scope") or OWNER_SCOPES.get(owner_type, "unknown")),
            "method": "manual",
            "confidence": str(override.get("confidence") or "medium"),
            "qid": "",
            "district": str(override.get("district") or ""),
            "local_level_id": "",
            "evidence_url": str(override.get("evidence_url") or ""),
            "evidence_note": str(override.get("evidence_note") or "Curated owner seed."),
        }

    items = wikidata_by_host.get(apex, [])
    for item in items:
        owner_type, scope = classify_description(item.get("description"))
        if owner_type == "unknown":
            continue
        return {
            "apex_hostname": apex,
            "owner_label": str(item.get("label") or ""),
            "owner_type": owner_type,
            "owner_scope": scope,
            "method": "wikidata_p856",
            "confidence": "high" if item.get("description") else "medium",
            "qid": str(item.get("qid") or ""),
            "district": str(item.get("district") or ""),
            "local_level_id": "",
            "evidence_url": "https://www.wikidata.org/wiki/" + str(item.get("qid") or ""),
            "evidence_note": str(item.get("description") or ""),
        }

    return {
        "apex_hostname": apex,
        "owner_label": "",
        "owner_type": "unknown",
        "owner_scope": "unknown",
        "method": "unclassified",
        "confidence": "none",
        "qid": "",
        "district": "",
        "local_level_id": "",
        "evidence_url": "",
        "evidence_note": "No committed source names an owner for this apex hostname.",
    }


def write_document(document: dict, dataset_dir: Path | None = None) -> Path:
    root = dataset_dir or paths.DATASET_DIR
    path = root / "entities.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
