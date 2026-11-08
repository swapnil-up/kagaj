from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

CRT_SH_URL = 'https://crt.sh/?q=%25.gov.np&output=json'
USER_AGENT = 'govweb-passive-audit/1.0 (Kagaj public-infrastructure research; https://github.com/swapnil-up/translation)'
DEFAULT_CACHE = paths.CACHE_DIR / 'crtsh.json'


def normalize_name(value: str) -> str:
    """Apply the roster's whitespace-collapse and Unicode case-fold rules."""
    return ' '.join(str(value).split()).casefold()


def domain_slug(value: str) -> str:
    """Convert a display name to the exact hyphenated DNS-label form."""
    return re.sub(r'\s+', '-', normalize_name(value).strip())


def normalize_hostname(value: str) -> str | None:
    value = value.strip().lower().rstrip('.')
    if value.startswith('*.'):
        value = value[2:]
    if not value or '/' in value or ':' in value or '*' in value:
        return None
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError:
        return None
    if len(value) > 253 or not value.endswith('.gov.np'):
        return None
    labels = value.split('.')
    if len(labels) < 3 or any(not label or len(label) > 63 for label in labels):
        return None
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label) for label in labels):
        return None
    return value


def extract_hostnames(records: list[dict[str, Any]]) -> list[str]:
    """Extract distinct DNS names from crt.sh name_value/common_name fields."""
    found: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        values = []
        for field in ('name_value', 'common_name'):
            value = record.get(field)
            if isinstance(value, str):
                values.extend(value.splitlines())
        for value in values:
            hostname = normalize_hostname(value)
            if hostname:
                found.add(hostname)
    return sorted(found)


def _roster_key(record: dict[str, Any]) -> tuple[str, str]:
    name = record.get('normalized_name') or normalize_name(record.get('name', ''))
    district = record.get('normalized_district') or normalize_name(record.get('district', ''))
    return normalize_name(name), normalize_name(district)


def _validate_roster(roster: list[dict[str, Any]]) -> None:
    for index, record in enumerate(roster):
        if not isinstance(record, dict) or not record.get('name'):
            raise ValueError(f'Invalid roster record at index {index}')
        if not record.get('municipality_id'):
            raise ValueError(f'Missing municipality_id at index {index}')


def match_hostnames(
    roster: list[dict[str, Any]], hostnames: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Match only exact municipality and district DNS labels.

    Both municipality and district must be represented as complete DNS labels.
    Name-only matching is permitted only for roster records without a district,
    and only when that municipality name is unique in the entire roster.
    No fuzzy, substring, geographic, or semantic matching is performed.
    """
    _validate_roster(roster)
    name_counts: dict[str, int] = defaultdict(int)
    for record in roster:
        name, _ = _roster_key(record)
        name_counts[name] += 1

    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in roster:
        index[_roster_key(record)].append(record)

    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ambiguous: dict[str, list[str]] = defaultdict(list)
    hostname_details: dict[str, list[str]] = defaultdict(list)

    for hostname in sorted(set(hostnames)):
        normalized = normalize_hostname(hostname)
        if not normalized:
            continue
        labels = set(normalized.split('.')[:-2])
        matches: list[dict[str, Any]] = []
        for record in roster:
            name, district = _roster_key(record)
            name_label = domain_slug(name)
            district_label = domain_slug(district)
            if not name_label:
                continue
            if district_label:
                # Require the exact municipality.district.gov.np name.
                # Reject www, portal, and other prefixed subdomains as
                # separate municipality domain candidates.
                if labels == {name_label, district_label}:
                    matches.append(record)
            elif name_counts[name] == 1 and labels == {name_label}:
                # Name-only matching is allowed only for a unique roster
                # name with no district and an exact DNS-label match.
                matches.append(record)

        if len(matches) == 1:
            record = matches[0]
            mid = str(record['municipality_id'])
            candidates[mid].append(record)
            hostname_details[mid].append(normalized)
        elif len(matches) > 1:
            ambiguous[normalized] = sorted(str(r['municipality_id']) for r in matches)

    output = []
    mapped_ids = set(candidates)
    for record in roster:
        mid = str(record['municipality_id'])
        domains = sorted(set(hostname_details.get(mid, [])))
        output.append({
            'municipality_id': mid,
            'province_id': str(record.get('province_id', '')),
            'district_id': str(record.get('district_id', '')),
            'province': record.get('province', ''),
            'district': record.get('district', ''),
            'municipality': record['name'],
            'domains': domains,
            'website_urls': [f'https://{domain}' for domain in domains],
            'mapping_method': 'crtsh_exact_municipality_and_district' if domains else None,
            'mapping_confidence': 'high' if domains else None,
            'status': 'mapped' if domains else 'unresolved',
            'source': 'crt.sh',
            'source_url': CRT_SH_URL,
        })

    mapped = len(mapped_ids)
    total = len(roster)
    coverage = {
        'source': 'crt.sh',
        'source_url': CRT_SH_URL,
        'roster_count': total,
        'mapped_count': mapped,
        'unresolved_count': total - mapped,
        'ambiguous_hostname_count': len(ambiguous),
        'unique_hostname_count': len(set(hostnames)),
        'coverage_percent': round(mapped * 100 / total, 2) if total else 0.0,
        'ambiguous_hostnames': [
            {'hostname': host, 'municipality_ids': ids}
            for host, ids in sorted(ambiguous.items())
        ],
        'matching_policy': 'Exact normalized municipality and district DNS labels; unique name-only matching only when district is absent from the roster record. No fuzzy matching.',
    }
    return output, coverage


def load_fixture(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError('crt.sh response must be a JSON array')
    return data


def fetch_crtsh(
    cache_path: str | Path = DEFAULT_CACHE,
    *,
    cache_max_age: int = 86400,
    timeout: int = 60,
    delay_seconds: float = 1.0,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch crt.sh once, with a persistent cache and identifying User-Agent."""
    cache = Path(cache_path)
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age <= cache_max_age:
            return load_fixture(cache), 'cache'

    request = urllib.request.Request(
        CRT_SH_URL,
        headers={
            'User-Agent': USER_AGENT,
            'Accept': 'application/json',
        },
    )
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f'crt.sh returned HTTP {response.status}')
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f'crt.sh collection failed: {exc}') from exc

    try:
        records = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError('crt.sh returned invalid JSON') from exc
    if not isinstance(records, list):
        raise RuntimeError('crt.sh response was not a JSON array')

    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(cache.suffix + '.tmp')
    temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(cache)
    return records, 'network'


def build_outputs(
    roster: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    fetched_at: str | None = None,
    cache_status: str = 'fixture',
) -> tuple[dict[str, Any], dict[str, Any]]:
    hostnames = extract_hostnames(records)
    mappings, coverage = match_hostnames(roster, hostnames)
    timestamp = fetched_at or datetime.now(timezone.utc).isoformat()
    source_hash = hashlib.sha256(
        json.dumps(records, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ).hexdigest()
    mapping_document = {
        'schema_version': 1,
        'source': 'crt.sh',
        'source_url': CRT_SH_URL,
        'fetched_at': timestamp,
        'cache_status': cache_status,
        'source_sha256': source_hash,
        'mappings': mappings,
    }
    coverage.update({
        'fetched_at': timestamp,
        'cache_status': cache_status,
        'source_sha256': source_hash,
    })
    return mapping_document, coverage


def write_json(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination)
