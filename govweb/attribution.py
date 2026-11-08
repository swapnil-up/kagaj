"""Evidence-bearing attribution of hostnames to local levels.

Attribution is a separate join, never an inference: every link records the
rule that produced it, a confidence level, and a citable evidence URL. A local
level with no discoverable hostname is reported as unresolved rather than
silently dropped, so the coverage denominator stays honest.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import paths

WIKIDATA_SOURCE = paths.SOURCE_DIR / "wikidata_nepal_websites.json"
DIRECTORY_SOURCE = paths.SOURCE_DIR / "localbody_directory.json"
OSM_SOURCE = paths.SOURCE_DIR / "osm_np_local_levels.json"
WIKIDATA_QUERY = """
SELECT ?item ?itemLabel ?itemDescription ?website ?districtLabel WHERE {
  ?item wdt:P17 wd:Q837 ;
        wdt:P856 ?website .
  OPTIONAL { ?item wdt:P131 ?district . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""
WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_QUERY_URL = (
    WIKIDATA_ENDPOINT + "?" + urllib.parse.urlencode({"query": WIKIDATA_QUERY, "format": "json"})
)
ADJUDICATION_FILE = paths.DATASET_DIR / "roster_adjudication.json"
OVERRIDES_FILE = paths.DATASET_DIR / "attribution_overrides.json"

SUFFIX_WORDS = frozenset(
    {
        "rural",
        "municipality",
        "municiapality",
        "municiaplity",
        "municpality",
        "metropolitan",
        "metropolitian",
        "metropolis",
        "submetropolitan",
        "submetropolitian",
        "sub",
        "city",
        "village",
        "nagar",
        "palika",
        "nagarpalika",
        "gaun",
        "gaunpalika",
    }
)

DISTRICT_ALIASES = {
    "kapilbastu": "kapilvastu",
    "dhanusha": "dhanusa",
    "tanahu": "tanahun",
    "pachthar": "panchthar",
    "tehrathum": "terhathum",
    "chitawan": "chitwan",
    "makawanpur": "makwanpur",
    "sindhupalchowk": "sindhupalchok",
    "rukum east": "eastern rukum",
    "rukum west": "western rukum",
    "nawalparasi east": "nawalpur",
    "nawalparasi west": "parasi",
}

PROVINCE_OR_ZONE_WORDS = frozenset(
    {
        "nepal",
        "koshi",
        "kosi",
        "madhesh",
        "madhes",
        "bagmati",
        "gandaki",
        "lumbini",
        "karnali",
        "sudurpashchim",
        "sudurpaschim",
        "province",
        "zone",
        "pradesh",
    }
)

SLUG_PREFIXES = ("munnp", "mun", "www", "nepal")
SLUG_SUFFIXES = (
    "municipality",
    "mun",
    "nagarpalika",
    "gaunpalika",
    "submetropolitan",
    "submetro",
    "metropolitan",
    "rm",
    "mc",
    "bids",
    "bds",
    "vdc",
    "ddc",
    "office",
    "gov",
)

BLOCKED_SLUGS = frozenset(
    {
        "gandaki",
        "bagmati",
        "koshi",
        "kosi",
        "lumbini",
        "karnali",
        "madhesh",
        "sudurpashchim",
        "nepal",
        "government",
        "doit",
        "nepalpolice",
        "election",
        "oag",
        "psc",
        "ssf",
        "ird",
        "dpr",
    }
)

# District coordination committees, district offices and other agencies publish
# pages for many local levels. Those pages are not the local level's own site and
# must never be attributed to it as its hostname.
NON_LOCAL_PREFIXES = (
    "ddc",
    "dado",
    "dfo",
    "dpho",
    "csidb",
    "rltc",
    "rvl",
    "rppl",
    "etck",
    "mof",
    "moi",
    "doi",
    "ird",
    "dpr",
    "doe",
    "dofe",
    "nepalpolice",
    "aqo",
    "cjcc",
    "oag",
    "psc",
    "ssf",
)

METHOD_RANK = {
    "manual": 6,
    "localbody_directory": 5,
    "wikidata_p856": 4,
    "ct_hostname_slug": 3,
    "osm_website": 2,
}
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize_name(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", _ascii(str(text)).lower())
    return " ".join(word for word in cleaned.split() if word not in SUFFIX_WORDS)


def compact(text: str) -> str:
    return normalize_name(text).replace(" ", "")


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def district_key(text: str | None) -> str | None:
    if not text:
        return None
    value = _ascii(str(text)).lower().replace(" district", "").strip()
    value = re.sub(r"[^a-z ]", " ", value)
    value = " ".join(value.split())
    if not value or value in PROVINCE_OR_ZONE_WORDS:
        return None
    if any(word in PROVINCE_OR_ZONE_WORDS for word in value.split() if word != "district"):
        if value not in DISTRICT_ALIASES:
            return None
    return DISTRICT_ALIASES.get(value, value)


def hostname_from_url(url: str | None) -> str:
    if not url:
        return ""
    candidate = str(url).strip()
    if "://" not in candidate:
        candidate = "http://" + candidate
    try:
        host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    if host.startswith("www.") and host.count(".") >= 3:
        host = host[4:]
    return host


def is_gov_np(hostname: str) -> bool:
    return hostname.endswith(".gov.np")


def is_local_level_hostname(hostname: str) -> bool:
    """Reject district/agency hosts that merely publish a local-level page."""
    if not is_gov_np(hostname):
        return False
    label = hostname.split(".")[0]
    return not any(label.startswith(prefix) for prefix in NON_LOCAL_PREFIXES)


def slug_variants(label: str) -> set[str]:
    """All plausible local-level slugs hiding in one DNS label."""
    label = label.lower()
    variants = {label}
    frontier = [label]
    while frontier:
        current = frontier.pop()
        for prefix in SLUG_PREFIXES:
            if current.startswith(prefix) and len(current) - len(prefix) >= 4:
                trimmed = current[len(prefix) :]
                if trimmed not in variants:
                    variants.add(trimmed)
                    frontier.append(trimmed)
        for suffix in SLUG_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 4:
                trimmed = current[: -len(suffix)]
                if trimmed not in variants:
                    variants.add(trimmed)
                    frontier.append(trimmed)
    return variants


def load_roster(dataset_dir: Path | None = None) -> list[dict]:
    root = dataset_dir or paths.DATASET_DIR
    return json.loads((root / "roster.json").read_text(encoding="utf-8"))


def load_adjudication(dataset_dir: Path | None = None) -> dict[str, dict]:
    root = dataset_dir or paths.DATASET_DIR
    path = root / "roster_adjudication.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(record["local_level_id"]): record
        for record in document.get("records", [])
        if record.get("status") in {"superseded", "duplicate", "misplaced"}
    }


def load_overrides(dataset_dir: Path | None = None) -> dict[str, list[dict]]:
    """Manual corrections applied after the automatic sources.

    ``reject`` drops a link that a source proposed but the evidence does not
    support; ``accept`` adds a link backed by a hand-checked source.
    """
    root = dataset_dir or paths.DATASET_DIR
    path = root / "attribution_overrides.json"
    if not path.is_file():
        return {"reject": [], "accept": []}
    document = json.loads(path.read_text(encoding="utf-8"))
    return {
        "reject": [entry for entry in document.get("reject", []) if isinstance(entry, dict)],
        "accept": [entry for entry in document.get("accept", []) if isinstance(entry, dict)],
    }


def fetch_wikidata(timeout: int = 180) -> list[dict]:
    """Fetch every Wikidata item in Nepal with an official website (P856)."""
    request = urllib.request.Request(
        WIKIDATA_QUERY_URL,
        headers={"User-Agent": "kagaj-govweb/0.1 (research; https://github.com/)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    items = []
    for binding in payload["results"]["bindings"]:
        items.append(
            {
                "qid": binding["item"]["value"].rsplit("/", 1)[-1],
                "label": binding["itemLabel"]["value"],
                "description": binding.get("itemDescription", {}).get("value"),
                "website": binding["website"]["value"],
                "district": binding.get("districtLabel", {}).get("value"),
            }
        )
    items.sort(key=lambda item: item["qid"])
    return items


def write_wikidata_source(
    items: list[dict],
    path: Path | None = None,
    *,
    fetched_at: str | None = None,
) -> Path:
    target = path or WIKIDATA_SOURCE
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": "1.0",
        "source": "Wikidata Query Service",
        "source_url": WIKIDATA_ENDPOINT,
        "query": WIKIDATA_QUERY.strip(),
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "item_count": len(items),
        "items": items,
    }
    target.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return target


def load_wikidata(path: Path | None = None) -> list[dict]:
    source = path or WIKIDATA_SOURCE
    if not source.is_file():
        return []
    document = json.loads(source.read_text(encoding="utf-8"))
    records = document.get("items", document) if isinstance(document, dict) else document
    return [record for record in records if isinstance(record, dict)]


def load_directory(path: Path | None = None) -> list[dict]:
    source = path or DIRECTORY_SOURCE
    if not source.is_file():
        return []
    document = json.loads(source.read_text(encoding="utf-8"))
    records = document.get("rows", document) if isinstance(document, dict) else document
    return [record for record in records if isinstance(record, dict)]


def load_osm_websites(path: Path | None = None) -> list[dict]:
    source = path or OSM_SOURCE
    if not source.is_file():
        return []
    document = json.loads(source.read_text(encoding="utf-8"))
    records = document.get("relations", []) if isinstance(document, dict) else document
    return [record for record in records if isinstance(record, dict) and record.get("website")]


def _roster_index(roster: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    by_district: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    for record in roster:
        by_district[district_key(record.get("district")) or ""].append(record)
        by_name[compact(record.get("name", ""))].append(record)
    return by_district, by_name


def _label_and_districts(item: dict) -> tuple[str, list[str]]:
    """Split ``Name, District`` and collect every usable district hint."""
    raw = str(item.get("label") or "")
    base, _, qualifier = raw.partition(",")
    label = compact(base)
    districts = []
    for value in (item.get("district"), qualifier):
        key = district_key(value)
        if key and key not in districts:
            districts.append(key)
    return label, districts


def _unique_best(
    scored: list[tuple[dict, float]],
    threshold: float,
) -> tuple[dict, float] | None:
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[1], reverse=True)
    if scored[0][1] < threshold:
        return None
    if len(scored) > 1 and scored[1][1] == scored[0][1]:
        return None
    return scored[0]


def _slug_match_records(
    hostname: str,
    records: list[dict],
) -> tuple[dict, str] | None:
    """Match a hostname slug against roster records, exact first, then containment."""
    label = hostname.split(".")[0]
    if label in BLOCKED_SLUGS or len(label) < 4:
        return None
    variants = {variant.replace(" ", "") for variant in slug_variants(label)}
    exact = [
        record
        for record in records
        if len(compact(record.get("name", "")).replace(" ", "")) >= 5
        and compact(record.get("name", "")).replace(" ", "") in variants
    ]
    unique = {str(record.get("municipality_id")): record for record in exact}
    if len(unique) == 1:
        return next(iter(unique.values())), "exact"
    if unique:
        return None
    contained = [
        record
        for record in records
        if len(compact(record.get("name", "")).replace(" ", "")) >= 7
        and any(
            compact(record.get("name", "")).replace(" ", "") in variant
            for variant in variants
        )
    ]
    unique = {str(record.get("municipality_id")): record for record in contained}
    if len(unique) == 1:
        return next(iter(unique.values())), "contains"
    return None


def match_wikidata_item(
    item: dict,
    by_district: dict[str, list[dict]],
    by_name: dict[str, list[dict]],
    all_records: list[dict] | None = None,
    hostname: str | None = None,
) -> tuple[dict, float, str] | None:
    """Return (roster record, score, confidence) for one Wikidata item.

    Wikidata descriptions are inconsistent: an item in Sankhuwasabha may carry
    ``Kosi Zone`` as its district, while the label itself says ``Madi,
    Sankhuwasabha``. We therefore try the item district and then the trailing
    label qualifier before falling back to a globally unique name match, and
    finally to the official website slug when the item is a local level.
    """
    label, districts = _label_and_districts(item)
    if not label:
        return None

    for district in districts:
        pool = by_district.get(district, [])
        best = _unique_best(
            [(record, similarity(compact(record.get("name", "")), label)) for record in pool],
            0.86,
        )
        if best:
            return best[0], best[1], "high" if best[1] == 1.0 else "medium"

    exact = by_name.get(label, [])
    if len(exact) == 1:
        return exact[0], 1.0, "high"
    if len(exact) > 1:
        return None

    if all_records:
        best = _unique_best(
            [(record, similarity(compact(record.get("name", "")), label)) for record in all_records],
            0.9,
        )
        if best:
            return best[0], best[1], "high" if best[1] == 1.0 else "medium"

    description = str(item.get("description") or "").lower()
    looks_local = any(
        word in description
        for word in ("municipalit", "metropolitan", "gaunpalika", "rural municipality", "city")
    )
    if hostname and all_records:
        slug = _slug_match_records(hostname, all_records)
        if slug and (slug[1] == "exact" or looks_local):
            record, kind = slug
            return record, 0.95 if kind == "exact" else 0.9, "medium"
    return None


def match_slug(
    hostname: str,
    by_name: dict[str, list[dict]],
) -> tuple[dict, float] | None:
    label = hostname.split(".")[0]
    if label in BLOCKED_SLUGS or len(label) < 4:
        return None
    best: tuple[dict, float] | None = None
    for variant in slug_variants(label):
        for name, records in by_name.items():
            score = similarity(name, variant)
            if len(records) == 1 and (best is None or score > best[1]):
                best = (records[0], score)
    if best and best[1] >= 0.9:
        return best
    return None


def hostname_matches_record(hostname: str, record: dict) -> bool:
    """Whether a hostname plausibly belongs to the named local level."""
    label = re.sub(r"[^a-z0-9]", "", hostname.split(".")[0].lower())
    if not label:
        return False
    if _name_slug_agrees(hostname, record.get("name", ""), district=record.get("district")):
        return True
    name = compact(record.get("name", "")).replace(" ", "")
    district = compact(record.get("district", "")).replace(" ", "")
    return bool(district and district in label and name[:4] and name[:4] in label)


def _vowel_squash(text: str) -> str:
    return re.sub(r"[aeiouwy]", "", text)


def _slug_stems(label: str, district: str | None = None) -> set[str]:
    """Every plausible local-level stem hiding in one DNS label.

    Registrars glue the type and the district to the name in any order, so
    ``trivenimunsalyan`` must reduce to ``triveni``.
    """
    base = re.sub(r"[^a-z0-9]", "", label.lower())
    stems = {base} if base else set()
    queue = [base] if base else []
    markers = (
        "municipality",
        "nagarpalika",
        "gaunpalika",
        "submetropolitan",
        "submetro",
        "metropolitan",
        "mun",
        "bids",
        "bds",
    )
    while queue:
        current = queue.pop()
        candidates = []
        for marker in markers:
            index = current.find(marker)
            if index != -1 and len(current) - len(marker) >= 4:
                candidates.append(current[:index] + current[index + len(marker) :])
        for prefix in SLUG_PREFIXES:
            if current.startswith(prefix) and len(current) - len(prefix) >= 4:
                candidates.append(current[len(prefix) :])
        for suffix in SLUG_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 4:
                candidates.append(current[: -len(suffix)])
        if district:
            key = district_key(district)
            if key:
                key_compact = key.replace(" ", "")
                if key_compact and key_compact in current and len(current) - len(key_compact) >= 4:
                    candidates.append(current.replace(key_compact, ""))
        for candidate in candidates:
            if candidate and candidate not in stems:
                stems.add(candidate)
                queue.append(candidate)
    return stems


def _name_slug_agrees(
    hostname: str,
    name: str,
    *,
    district: str | None = None,
    allow_prefix: bool = False,
) -> bool:
    """Whether a DNS label is a defensible rendering of a local-level name.

    Nepali transliteration is not standardized: ``Jaimuni`` registers as
    ``jaiminimun`` and ``Sunarya`` as ``surnaya``. The rules below accept those
    vowel and one-letter swaps while rejecting a slug that only shares a generic
    token such as ``kalika``.
    """
    target = compact(name).replace(" ", "")
    if not target:
        return False
    for stem in _slug_stems(hostname.split(".")[0], district):
        if not stem:
            continue
        if target == stem or _vowel_squash(target) == _vowel_squash(stem):
            return True
        if len(target) >= 5 and target in stem:
            return True
        score = similarity(stem, target)
        if score >= 0.9:
            return True
        if score >= 0.82 and stem[0] == target[0] and abs(len(stem) - len(target)) <= 1:
            return True
        if len(stem) >= 7 and stem in target:
            return True
        if allow_prefix and len(stem) >= 5 and target.startswith(stem):
            return True
    return False


def _district_in_hostname(hostname: str, district: str | None) -> bool:
    key = district_key(district)
    if not key:
        return False
    label = re.sub(r"[^a-z0-9]", "", hostname.split(".")[0].lower())
    key_compact = key.replace(" ", "")
    if len(key_compact) >= 5 and key_compact in label:
        return True
    if len(key_compact) >= 4 and (label.startswith(key_compact) or label.endswith(key_compact)):
        return True
    squashed_key = _vowel_squash(key_compact)
    return bool(len(squashed_key) >= 6 and squashed_key in _vowel_squash(label))


def _names_agree(left: str, right: str) -> bool:
    left_key = compact(left)
    right_key = compact(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if _vowel_squash(left_key.replace(" ", "")) == _vowel_squash(right_key.replace(" ", "")):
        return True
    if similarity(left_key, right_key) >= 0.82:
        return True
    left_tokens = {token for token in left_key.split() if len(token) >= 5}
    right_tokens = {token for token in right_key.split() if len(token) >= 5}
    return bool(left_tokens and right_tokens and (left_tokens <= right_tokens or right_tokens <= left_tokens))


def match_directory_row(
    row: dict,
    by_name: dict[str, list[dict]],
    all_records: list[dict],
) -> tuple[dict, float, str] | None:
    """Match one directory row to a roster record.

    The directory's English names are close to the gazetted names, but some are
    ambiguous across districts, some omit a qualifier, and many use a different
    transliteration. The row's own website is used to disambiguate.
    """
    name = compact(row.get("name_en", ""))
    if not name:
        return None
    hostname = hostname_from_url(row.get("website"))
    candidates = by_name.get(name, [])
    if hostname:
        named_district = [
            record
            for record in all_records
            if _district_in_hostname(hostname, record.get("district"))
            and _names_agree(name, record.get("name", ""))
        ]
        unique_named = {str(record.get("municipality_id")): record for record in named_district}
        candidate_ids = {str(record.get("municipality_id")) for record in candidates}
        if len(unique_named) == 1 and not (candidate_ids & set(unique_named)):
            return next(iter(unique_named.values())), 0.9, "fuzzy"
    if not candidates:
        tokens = set(name.split())
        candidates = [
            record
            for record in all_records
            if (record_tokens := set(compact(record.get("name", "")).split()))
            and record_tokens <= tokens
            and any(len(token) >= 4 for token in record_tokens)
        ]
    if not candidates:
        scored = sorted(
            (
                (record, similarity(compact(record.get("name", "")), name))
                for record in all_records
            ),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if scored and scored[0][1] >= 0.8 and (
            len(scored) == 1 or scored[1][1] <= scored[0][1] - 0.03
        ):
            candidates = [scored[0][0]]
    unique = {str(record.get("municipality_id")): record for record in candidates}
    if len(unique) == 1:
        record = next(iter(unique.values()))
        exact = compact(record.get("name", "")) == name or (
            _vowel_squash(compact(record.get("name", "")).replace(" ", ""))
            == _vowel_squash(name.replace(" ", ""))
        )
        return record, 1.0 if exact else 0.9, "exact" if exact else "fuzzy"
    if unique and hostname:
        by_district = [
            record for record in unique.values() if _district_in_hostname(hostname, record.get("district"))
        ]
        narrowed = {str(record.get("municipality_id")): record for record in by_district}
        if len(narrowed) > 1:
            narrowed = {
                key: record
                for key, record in narrowed.items()
                if _name_slug_agrees(hostname, record.get("name", ""), district=record.get("district"))
                or _name_slug_agrees(
                    hostname,
                    row.get("name_en", ""),
                    district=record.get("district"),
                    allow_prefix=True,
                )
            }
        if len(narrowed) == 1:
            return next(iter(narrowed.values())), 1.0, "exact"
        corroborated = {
            str(record.get("municipality_id")): record
            for record in unique.values()
            if hostname_matches_record(hostname, record)
            or _name_slug_agrees(
                hostname,
                row.get("name_en", ""),
                district=record.get("district"),
                allow_prefix=True,
            )
        }
        if len(corroborated) == 1:
            return next(iter(corroborated.values())), 1.0, "exact"
        return None
    if unique:
        return None
    best = _unique_best(
        [(record, similarity(compact(record.get("name", "")), name)) for record in all_records],
        0.86,
    )
    if best:
        return best[0], best[1], "fuzzy"
    return None


def _record(
    roster_record: dict,
    *,
    hostname: str,
    website_url: str,
    method: str,
    confidence: str,
    evidence_url: str,
    evidence_note: str,
    decided_at: str,
) -> dict:
    return {
        "local_level_id": str(roster_record.get("municipality_id")),
        "local_level_name": roster_record.get("name"),
        "district": roster_record.get("district"),
        "province": roster_record.get("province"),
        "hostname": hostname,
        "website_url": website_url,
        "method": method,
        "confidence": confidence,
        "status": "mapped" if hostname else "unresolved",
        "evidence_url": evidence_url,
        "evidence_note": evidence_note,
        "decided_at": decided_at,
    }


def attribute(
    roster: list[dict],
    wikidata: list[dict],
    hostnames: list[str],
    *,
    directory: list[dict] | None = None,
    osm_websites: list[dict] | None = None,
    adjudication: dict[str, dict] | None = None,
    overrides: dict[str, list[dict]] | None = None,
    decided_at: str | None = None,
) -> dict:
    """Build the attribution document.

    ``roster`` may include superseded records; they are excluded from the
    denominator and never attributed. Sources are merged with the best-ranked
    method winning each hostname, so one host can never be claimed by two local
    levels.
    """
    excluded = adjudication if adjudication is not None else load_adjudication()
    stamp = decided_at or datetime.now(timezone.utc).date().isoformat()
    active = [r for r in roster if str(r.get("municipality_id")) not in excluded]
    by_district, by_name = _roster_index(active)

    links: dict[tuple[str, str], dict] = {}
    owners: dict[str, str] = {}

    def add(record: dict, key: str, payload: dict) -> None:
        hostname = payload["hostname"]
        owner = owners.get(hostname)
        if owner is not None and owner != key:
            existing = links.get((owner, hostname))
            if existing is not None and METHOD_RANK.get(existing["method"], 0) >= METHOD_RANK.get(
                payload["method"], 0
            ):
                return
            links.pop((owner, hostname), None)
        existing = links.get((key, hostname))
        if existing is None:
            links[(key, hostname)] = payload
            owners[hostname] = key
            return
        better = (
            METHOD_RANK.get(payload["method"], 0) > METHOD_RANK.get(existing["method"], 0)
            or CONFIDENCE_RANK.get(payload["confidence"], 0) > CONFIDENCE_RANK.get(existing["confidence"], 0)
        )
        if better:
            links[(key, hostname)] = payload

    for row in sorted(directory or [], key=lambda value: int(value.get("serial") or 0)):
        hostname = hostname_from_url(row.get("website"))
        if not hostname or not is_local_level_hostname(hostname):
            continue
        if hostname.split(".")[0] in BLOCKED_SLUGS:
            continue
        match = match_directory_row(row, by_name, active)
        if match is None:
            continue
        record, score, kind = match
        if not hostname_matches_record(hostname, record) and not _name_slug_agrees(
            hostname,
            row.get("name_en", ""),
            district=record.get("district"),
            allow_prefix=True,
        ):
            continue
        key = str(record.get("municipality_id"))
        add(
            record,
            key,
            _record(
                record,
                hostname=hostname,
                website_url=row.get("website") or "",
                method="localbody_directory",
                confidence="high" if kind == "exact" else "medium",
                evidence_url="http://eoffice.mahalaxmimun.gov.np/dcc-localbody-list",
                evidence_note=(
                    f"Local-body directory row {row.get('serial')}: "
                    f"{row.get('name_en')!r} ({row.get('wards')} wards, name score={score:.2f})"
                ),
                decided_at=stamp,
            ),
        )

    for item in sorted(wikidata, key=lambda value: str(value.get("qid", ""))):
        hostname = hostname_from_url(item.get("website"))
        match = match_wikidata_item(item, by_district, by_name, active, hostname)
        if match is None:
            continue
        record, score, confidence = match
        key = str(record.get("municipality_id"))
        if is_local_level_hostname(hostname):
            add(
                record,
                key,
                _record(
                    record,
                    hostname=hostname,
                    website_url=item.get("website") or "",
                    method="wikidata_p856",
                    confidence=confidence,
                    evidence_url=f"https://www.wikidata.org/wiki/{item.get('qid')}",
                    evidence_note=(
                        f"Wikidata P856 for {str(item.get('label') or '').split(',')[0]!r} "
                        f"(item district={item.get('district')!r}, name score={score:.2f})"
                    ),
                    decided_at=stamp,
                ),
            )

    apexes = sorted(
        {
            ".".join(hostname.split(".")[-3:])
            for hostname in hostnames
            if hostname.endswith(".gov.np")
        }
    )
    for hostname in apexes:
        match = match_slug(hostname, by_name)
        if match is None:
            continue
        record, score = match
        key = str(record.get("municipality_id"))
        add(
            record,
            key,
            _record(
                record,
                hostname=hostname,
                website_url=f"https://{hostname}/",
                method="ct_hostname_slug",
                confidence="high" if score == 1.0 else "medium",
                evidence_url="https://crt.sh/?q=%25.gov.np&output=json",
                evidence_note=f"Certificate Transparency hostname label matches the local-level name (score={score:.2f})",
                decided_at=stamp,
            ),
        )

    for relation in osm_websites or []:
        hostname = hostname_from_url(relation.get("website"))
        if not hostname or not is_local_level_hostname(hostname):
            continue
        slug = _slug_match_records(hostname, active)
        if slug is None:
            continue
        record, kind = slug
        key = str(record.get("municipality_id"))
        add(
            record,
            key,
            _record(
                record,
                hostname=hostname,
                website_url=relation.get("website") or "",
                method="osm_website",
                confidence="medium",
                evidence_url=f"https://www.openstreetmap.org/relation/{relation.get('osm_id')}",
                evidence_note=(
                    f"OpenStreetMap relation {relation.get('osm_id')} official website "
                    f"({relation.get('name_en') or relation.get('name')!r}, {kind} slug match)"
                ),
                decided_at=stamp,
            ),
        )

    records: list[dict] = []
    mapped_ids: set[str] = set()

    active_by_id = {str(record.get("municipality_id")): record for record in active}
    corrections = overrides if overrides is not None else load_overrides()
    for entry in corrections.get("reject", []):
        local_level_id = str(entry.get("local_level_id") or "")
        hostname = str(entry.get("hostname") or "").strip().lower().rstrip(".")
        if not local_level_id or not hostname:
            continue
        links.pop((local_level_id, hostname), None)
        if owners.get(hostname) == local_level_id:
            del owners[hostname]
    for entry in corrections.get("accept", []):
        local_level_id = str(entry.get("local_level_id") or "")
        hostname = str(entry.get("hostname") or "").strip().lower().rstrip(".")
        record = active_by_id.get(local_level_id)
        if record is None or not hostname:
            continue
        add(
            record,
            local_level_id,
            _record(
                record,
                hostname=hostname,
                website_url=f"https://{hostname}/",
                method="manual",
                confidence=str(entry.get("confidence") or "medium"),
                evidence_url=str(entry.get("evidence_url") or ""),
                evidence_note=str(entry.get("evidence_note") or ""),
                decided_at=str(entry.get("decided_at") or stamp),
            ),
        )

    for payload in links.values():
        records.append(payload)
        mapped_ids.add(payload["local_level_id"])

    unresolved = []
    for record in active:
        key = str(record.get("municipality_id"))
        if key in mapped_ids:
            continue
        unresolved.append(
            _record(
                record,
                hostname="",
                website_url="",
                method="no_site_found",
                confidence="none",
                evidence_url="",
                evidence_note=(
                    "No .gov.np hostname matched by the local-body directory, Wikidata P856, "
                    "Certificate Transparency or OpenStreetMap."
                ),
                decided_at=stamp,
            )
        )

    records.sort(key=lambda row: (row["district"] or "", row["local_level_name"] or "", row["hostname"]))
    unresolved.sort(key=lambda row: (row["district"] or "", row["local_level_name"] or ""))

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roster_records": len(roster),
        "canonical_local_levels": len(active),
        "excluded_records": len(excluded),
        "mapped_local_levels": len(mapped_ids),
        "unresolved_local_levels": len(unresolved),
        "coverage_percent": round(100.0 * len(mapped_ids) / len(active), 2) if active else 0.0,
        "mapping_count": len(records),
        "methods": _method_counts(records),
        "records": records,
        "unresolved": unresolved,
    }


def _method_counts(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[record["method"]] += 1
    return dict(sorted(counts.items()))


def write_document(document: dict, dataset_dir: Path | None = None) -> Path:
    root = dataset_dir or paths.DATASET_DIR
    path = root / "attribution.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ct_hostnames(dataset_dir: Path | None = None) -> list[str]:
    root = dataset_dir or paths.DATASET_DIR
    path = root / "sources" / "crtsh_gov_np.json"
    if not path.is_file():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        for field in ("name_value", "common_name"):
            value = record.get(field)
            if not isinstance(value, str):
                continue
            for candidate in value.splitlines():
                candidate = candidate.strip().lower().rstrip(".")
                if candidate.startswith("*."):
                    candidate = candidate[2:]
                if candidate.endswith(".gov.np") and "/" not in candidate:
                    found.add(candidate)
    return sorted(found)
