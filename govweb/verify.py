"""Reconcile the roster, discovery inventory and per-host observation sets.

The report is deliberately about coverage and internal consistency: it records
what the collection reached, what it did not, and where the source roster
disagrees with the official count of 753 local levels. It never converts an
unreachable site into a passing measurement.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

DATASET_DIR = paths.DATASET_DIR

# Nepal has 753 local levels: 6 metropolitan cities, 11 sub-metropolitan
# cities, 276 municipalities and 460 rural municipalities.
OFFICIAL_TOTALS = {
    "metropolitan_city": 6,
    "sub_metropolitan_city": 11,
    "municipality": 276,
    "rural_municipality": 460,
}
OFFICIAL_TOTAL = sum(OFFICIAL_TOTALS.values())

OBSERVATION_FILES = {
    "tls": "observations/tls_observations.json",
    "http_headers": "observations/http_header_observations.json",
    "hosting": "observations/hosting_observations.json",
    "third_party_scripts": "observations/third_party_scripts.json",
    "dns_mail": "observations/dns_mail_observations.json",
    "robots": "observations/robots_observations.json",
}

_SPELLING = re.compile(r"munic[iy]?a?pality|municipality|municiapality|municpality", re.IGNORECASE)


def _load(relative: str) -> Any:
    path = DATASET_DIR / relative
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _observations(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, dict):
        values = document.get("observations", [])
    elif isinstance(document, list):
        values = document
    else:
        return []
    return [item for item in values if isinstance(item, dict)]


def local_level_type(name: str) -> str:
    """Classify a local level from its declared name.

    The roster is an external API and misspells several names, so the classifier
    normalises spelling before matching and keeps an ``unclassified`` bucket
    rather than guessing.
    """
    value = _SPELLING.sub("municipality", str(name or "")).lower()
    if "sub-metropolitan" in value or "sub metropolitan" in value:
        return "sub_metropolitan_city"
    if "rural" in value:
        return "rural_municipality"
    if "metropolitan" in value:
        return "metropolitan_city"
    if "municipality" in value:
        return "municipality"
    return "unclassified"


def _host(record: dict[str, Any]) -> str:
    for key in ("hostname", "site_hostname", "url", "robots_url"):
        value = record.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = value.strip().lower().rstrip(".")
        if "://" in candidate:
            from urllib.parse import urlparse

            candidate = (urlparse(candidate).hostname or "").lower().rstrip(".")
        if candidate:
            return candidate
    return ""


def roster_report(roster: list[dict[str, Any]]) -> dict[str, Any]:
    types = Counter(local_level_type(record.get("name", "")) for record in roster)
    pairs = Counter(
        (str(record.get("district", "")).strip().casefold(), str(record.get("name", "")).strip().casefold())
        for record in roster
    )
    duplicates = [
        {"district": district, "name": name, "count": count}
        for (district, name), count in sorted(pairs.items())
        if count > 1
    ]
    nonstandard = sorted(
        str(record.get("name", ""))
        for record in roster
        if local_level_type(record.get("name", "")) == "unclassified"
    )
    return {
        "records": len(roster),
        "official_total": OFFICIAL_TOTAL,
        "delta": len(roster) - OFFICIAL_TOTAL,
        "province_count": len({str(record.get("province_id")) for record in roster}),
        "district_count": len({str(record.get("district_id")) for record in roster}),
        "by_type": dict(sorted(types.items())),
        "official_by_type": OFFICIAL_TOTALS,
        "duplicate_district_name": duplicates,
        "unclassified_names": nonstandard,
    }


def _norm_host(host: str) -> str:
    value = str(host).strip().lower().rstrip(".")
    if value.startswith("www.") and value.count(".") >= 3:
        value = value[4:]
    return value


def verify() -> dict[str, Any]:
    roster = _load("roster.json")
    roster = roster if isinstance(roster, list) else []
    adjudication_document = _load("roster_adjudication.json")
    adjudication_document = adjudication_document if isinstance(adjudication_document, dict) else {}
    adjudication = {
        str(record.get("local_level_id")): record
        for record in adjudication_document.get("records", [])
        if isinstance(record, dict)
    }
    active_roster = [
        record
        for record in roster
        if str(record.get("municipality_id")) not in adjudication
    ]
    coverage = _load("website_coverage_crtsh.json")
    coverage = coverage if isinstance(coverage, dict) else {}
    sample = _load("tls_sample.json")
    sample_hosts = [
        str(host).lower().rstrip(".")
        for host in (sample.get("hostnames", []) if isinstance(sample, dict) else [])
        if isinstance(host, str)
    ]

    observations: dict[str, Any] = {}
    host_sets: dict[str, set[str]] = {}
    for name, relative in OBSERVATION_FILES.items():
        document = _load(relative)
        records = _observations(document)
        statuses = Counter(str(record.get("status", "unknown")) for record in records)
        document = document if isinstance(document, dict) else {}
        observations[name] = {
            "available": bool(records) or bool(document),
            "requested": document.get("requested_hostname_count") or document.get("requested_url_count"),
            "completed": len(records),
            "status_counts": dict(sorted(statuses.items())),
        }
        host_sets[name] = {_host(record) for record in records if _host(record)}

    crtsh = _load("sources/crtsh_gov_np.json")
    crtsh_hosts = set()
    for record in crtsh if isinstance(crtsh, list) else []:
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
                    crtsh_hosts.add(candidate)

    attribution_document = _load("attribution.json")
    attribution_document = attribution_document if isinstance(attribution_document, dict) else {}
    attribution_records = [
        record for record in attribution_document.get("records", []) if isinstance(record, dict)
    ]
    attribution_unresolved = [
        record for record in attribution_document.get("unresolved", []) if isinstance(record, dict)
    ]
    attributed_hosts = {
        _norm_host(record.get("hostname"))
        for record in attribution_records
        if record.get("hostname")
    }
    attributed_ids = {
        str(record.get("local_level_id")) for record in attribution_records if record.get("local_level_id")
    }
    active_ids = {str(record.get("municipality_id")) for record in active_roster}

    source_hosts = {
        str(host).lower().rstrip(".")
        for host in sample_hosts
    }
    source_hosts |= crtsh_hosts
    directory_document = _load("sources/localbody_directory.json")
    directory_rows = (
        directory_document.get("rows", []) if isinstance(directory_document, dict) else []
    )
    for row in directory_rows:
        if isinstance(row, dict) and isinstance(row.get("website"), str):
            from urllib.parse import urlparse

            host = (urlparse(row["website"]).hostname or "").lower().rstrip(".")
            if host:
                source_hosts.add(host)
    for relative, keys in (
        ("sources/wikidata_nepal_websites.json", ("items",)),
        ("sources/osm_np_local_levels.json", ("relations",)),
    ):
        document = _load(relative)
        values = document
        if isinstance(document, dict):
            values = document.get(keys[0], [])
        for record in values if isinstance(values, list) else []:
            if not isinstance(record, dict):
                continue
            website = record.get("website")
            if not isinstance(website, str):
                continue
            from urllib.parse import urlparse

            host = (urlparse(website).hostname or "").lower().rstrip(".")
            if host:
                source_hosts.add(host)

    source_hosts = {_norm_host(host) for host in source_hosts}
    overrides_document = _load("attribution_overrides.json")
    accept_entries = (
        overrides_document.get("accept", []) if isinstance(overrides_document, dict) else []
    )
    for entry in accept_entries if isinstance(accept_entries, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("hostname"), str):
            source_hosts.add(_norm_host(entry["hostname"]))

    roster_info = roster_report(active_roster)
    checks: list[dict[str, Any]] = []

    def check(identifier: str, ok: bool, detail: str, severity: str = "warn") -> None:
        checks.append(
            {
                "id": identifier,
                "status": "pass" if ok else severity,
                "detail": detail,
            }
        )

    check(
        "roster_total_matches_official_753",
        len(active_roster) == OFFICIAL_TOTAL,
        f"{len(roster)} roster records, {len(active_roster)} after adjudication, official total {OFFICIAL_TOTAL}",
    )
    check(
        "roster_adjudication_accounts_for_delta",
        len(roster) - len(active_roster) == len(adjudication),
        f"{len(adjudication)} adjudicated records against a roster delta of {len(roster) - len(active_roster)}",
        severity="fail",
    )
    check(
        "roster_province_count",
        roster_info["province_count"] == 7,
        f"{roster_info['province_count']} provinces",
    )
    check(
        "roster_district_count",
        roster_info["district_count"] == 77,
        f"{roster_info['district_count']} districts",
    )
    check(
        "roster_has_no_duplicate_district_name",
        not roster_info["duplicate_district_name"],
        f"{len(roster_info['duplicate_district_name'])} duplicate district+name pairs",
    )
    check(
        "roster_type_counts_match_official",
        all(roster_info["by_type"].get(key) == value for key, value in OFFICIAL_TOTALS.items()),
        f"observed {roster_info['by_type']} against official {OFFICIAL_TOTALS}",
    )
    check(
        "attribution_exists",
        bool(attribution_records or attribution_unresolved),
        f"{len(attribution_records)} mapped rows and {len(attribution_unresolved)} unresolved rows",
        severity="fail",
    )
    check(
        "attribution_covers_every_active_local_level",
        attributed_ids | {str(row.get("local_level_id")) for row in attribution_unresolved} == active_ids,
        "every active local level is either mapped or explicitly unresolved",
        severity="fail",
    )
    check(
        "attribution_never_uses_adjudicated_records",
        not (attributed_ids & set(adjudication)),
        f"{len(attributed_ids & set(adjudication))} adjudicated records were attributed",
        severity="fail",
    )
    duplicate_links = [
        hostname
        for hostname, count in Counter(
            str(record.get("hostname")).lower().rstrip(".")
            for record in attribution_records
            if record.get("hostname")
        ).items()
        if count > 1
    ]
    check(
        "attribution_has_no_duplicate_hostname_links",
        not duplicate_links,
        f"hostnames claimed by more than one local level: {duplicate_links}",
        severity="fail",
    )
    check(
        "attribution_hosts_are_gov_np",
        all(hostname.endswith(".gov.np") for hostname in attributed_hosts),
        f"{len(attributed_hosts)} attributed hostnames",
        severity="fail",
    )
    outside = sorted(attributed_hosts - source_hosts)
    check(
        "attribution_has_no_hostname_outside_discovery_sources",
        not outside,
        f"attributed hostnames absent from every committed source: {outside}",
        severity="fail",
    )
    rejected_still_linked = sorted(
        str(entry.get("hostname"))
        for entry in overrides_document.get("reject", [])
        if isinstance(entry, dict)
        and _norm_host(str(entry.get("hostname") or ""))
        in {_norm_host(record.get("hostname") or "") for record in attribution_records}
    ) if isinstance(overrides_document, dict) else []
    check(
        "attribution_rejections_are_not_linked",
        not rejected_still_linked,
        f"overridden rejections still attributed: {rejected_still_linked}",
        severity="fail",
    )
    unapplied_accepts = sorted(
        str(entry.get("local_level_id"))
        for entry in accept_entries
        if isinstance(entry, dict)
        and not any(
            str(record.get("local_level_id")) == str(entry.get("local_level_id"))
            and record.get("hostname") == entry.get("hostname")
            for record in attribution_records
        )
    )
    check(
        "attribution_acceptances_are_applied",
        not unapplied_accepts,
        f"manual acceptances missing from attribution: {unapplied_accepts}",
        severity="fail",
    )
    missing_evidence = sorted(
        str(record.get("local_level_id"))
        for record in attribution_records
        if not (record.get("evidence_url") and record.get("decided_at") and record.get("method"))
    )
    check(
        "attribution_rows_carry_evidence",
        not missing_evidence,
        f"{len(missing_evidence)} mapped rows lack method, evidence URL or decision date",
        severity="fail",
    )
    method_total = sum(attribution_document.get("methods", {}).values())
    check(
        "attribution_method_counts_reconcile",
        method_total == len(attribution_records),
        f"{method_total} method counts against {len(attribution_records)} mapped rows",
        severity="fail",
    )
    expected_coverage = (
        round(100.0 * len(attributed_ids) / len(active_roster), 2) if active_roster else 0.0
    )
    check(
        "attribution_coverage_matches_its_own_counts",
        attribution_document.get("coverage_percent") == expected_coverage,
        f"declared {attribution_document.get('coverage_percent')}%, computed {expected_coverage}%",
        severity="fail",
    )
    check(
        "sample_within_declared_limit",
        len(sample_hosts) <= 20,
        f"{len(sample_hosts)} sampled hostnames",
    )
    unknown_observations = sorted(
        name for name, hosts in host_sets.items() if hosts - source_hosts and hosts
    )
    check(
        "observations_stay_within_discovered_inventory",
        not unknown_observations,
        f"datasets with hostnames absent from every discovery source: {unknown_observations}",
        severity="fail",
    )

    return {
        "schema_version": 1,
        "report_type": "govweb_reconciliation",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roster": {
            **roster_info,
            "raw_records": len(roster),
            "adjudicated_records": len(adjudication),
        },
        "discovery": {
            "ct_hostname_count": len(crtsh_hosts),
            "source_hostname_count": len(source_hosts),
            "coverage": {
                key: coverage.get(key)
                for key in (
                    "roster_count",
                    "mapped_count",
                    "unresolved_count",
                    "coverage_percent",
                    "matching_policy",
                )
            },
            "attribution": {
                "canonical_local_levels": attribution_document.get("canonical_local_levels"),
                "mapped_local_levels": attribution_document.get("mapped_local_levels"),
                "unresolved_local_levels": attribution_document.get("unresolved_local_levels"),
                "coverage_percent": attribution_document.get("coverage_percent"),
                "methods": attribution_document.get("methods"),
                "mapped_hostname_count": len(attributed_hosts),
            },
        },
        "observations": observations,
        "checks": checks,
    }


def write_report() -> tuple[Path, dict[str, Any]]:
    report = verify()
    path = DATASET_DIR / "reconciliation.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, report
