from __future__ import annotations

import argparse
import base64
import hashlib
import json
import socket
import ssl
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import paths

DEFAULT_MAPPING = paths.DATASET_DIR / 'website_mappings_crtsh.json'
DEFAULT_CT_CACHE = paths.CACHE_DIR / 'crtsh.json'
DEFAULT_SAMPLE = paths.DATASET_DIR / 'tls_sample.json'
DEFAULT_CACHE = paths.CACHE_DIR / 'tls'
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / 'tls_observations.json'
USER_AGENT = 'govweb-passive-audit/1.0 (Kagaj public-infrastructure research; https://github.com/swapnil-up/translation)'
SCHEMA_VERSION = 1
DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 10
DEFAULT_CACHE_AGE = 604800


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: str | Path, data: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    temporary.replace(destination)


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding='utf-8') as handle:
        return json.load(handle)


def valid_hostname(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip().lower().rstrip('.')
    if not value or len(value) > 253 or '/' in value or ':' in value:
        return False
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    labels = value.split('.')
    if len(labels) < 2:
        return False
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label.startswith('-') or label.endswith('-'):
            return False
        if not all(c.isalnum() or c == '-' for c in label):
            return False
    return True


def discovered_hostnames(mapping_path: str | Path = DEFAULT_MAPPING,
                         ct_cache_path: str | Path = DEFAULT_CT_CACHE) -> list[str]:
    """Read actual discovered names; never synthesize names from municipality data."""
    found: set[str] = set()
    mapping = Path(mapping_path)
    if mapping.exists():
        document = load_json(mapping)
        records = document.get('mappings', []) if isinstance(document, dict) else []
        if not isinstance(records, list):
            raise ValueError('Mapping document mappings must be an array')
        for record in records:
            if not isinstance(record, dict):
                continue
            domains = record.get('domains', [])
            if isinstance(domains, list):
                found.update(domain.lower().rstrip('.') for domain in domains
                             if valid_hostname(domain))

    # The mapping inventory can legitimately contain zero exact matches.
    # In that case, use the actual CT response rather than inventing names.
    if not found:
        cache = Path(ct_cache_path)
        if not cache.exists():
            raise FileNotFoundError(
                'Neither discovered mapping hostnames nor the CT cache is available'
            )
        records = load_json(cache)
        if not isinstance(records, list):
            raise ValueError('CT cache must contain a JSON array')
        for record in records:
            if not isinstance(record, dict):
                continue
            for field in ('name_value', 'common_name'):
                value = record.get(field)
                if not isinstance(value, str):
                    continue
                for candidate in value.splitlines():
                    candidate = candidate.strip().lower().rstrip('.')
                    if candidate.startswith('*.'):
                        candidate = candidate[2:]
                    if valid_hostname(candidate) and candidate.endswith('.gov.np'):
                        found.add(candidate)

    return sorted(found)


def select_sample(hostnames: list[str], size: int = 20) -> list[str]:
    """Select the first N entries from a sorted, unique discovered inventory."""
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError('Sample size must be a positive integer')
    normalized = sorted({h.lower().rstrip('.') for h in hostnames if valid_hostname(h)})
    if not normalized:
        raise ValueError('No valid discovered hostnames are available')
    return normalized[:size]


def create_sample(output: str | Path = DEFAULT_SAMPLE,
                  mapping_path: str | Path = DEFAULT_MAPPING,
                  ct_cache_path: str | Path = DEFAULT_CT_CACHE,
                  size: int = 20) -> dict[str, Any]:
    hostnames = discovered_hostnames(mapping_path, ct_cache_path)
    sample = select_sample(hostnames, size)
    document = {
        'schema_version': SCHEMA_VERSION,
        'source': 'discovered Certificate Transparency hostname inventory',
        'source_files': [str(Path(mapping_path)), str(Path(ct_cache_path))],
        'selection_policy': 'lexicographically first unique normalized discovered hostnames',
        'inventory_count': len(hostnames),
        'requested_sample_size': size,
        'sample_count': len(sample),
        'created_at': utc_now(),
        'hostnames': sample,
    }
    write_json(output, document)
    return document


def decode_certificate(der_certificate: bytes) -> dict[str, Any]:
    """Decode a DER certificate using Python's bundled OpenSSL decoder."""
    pem = ssl.DER_cert_to_PEM_cert(der_certificate)
    with tempfile.NamedTemporaryFile(mode='w', encoding='ascii', suffix='.pem') as handle:
        handle.write(pem)
        handle.flush()
        return ssl._ssl._test_decode_cert(handle.name)


def _issuer_string(certificate: dict[str, Any]) -> str | None:
    issuer = certificate.get('issuer', ())
    parts = []
    for group in issuer:
        for key, value in group:
            parts.append(f'{key}={value}')
    return ', '.join(parts) or None


def _subject_string(certificate: dict[str, Any]) -> str | None:
    subject = certificate.get('subject', ())
    parts = []
    for group in subject:
        for key, value in group:
            parts.append(f'{key}={value}')
    return ', '.join(parts) or None


def _certificate_dates(certificate: dict[str, Any]) -> tuple[str | None, str | None]:
    return certificate.get('notBefore'), certificate.get('notAfter')


def _dns_pattern_matches(pattern: str, hostname: str) -> bool:
    """Match an exact DNS name or a single-label leftmost wildcard."""
    pattern = pattern.rstrip('.').lower()
    hostname = hostname.rstrip('.').lower()
    if pattern.startswith('*.'):
        suffix = pattern[2:]
        if not suffix or hostname.count('.') != suffix.count('.') + 1:
            return False
        return hostname.endswith('.' + suffix)
    return pattern == hostname


def _certificate_matches_hostname(certificate: dict[str, Any], hostname: str) -> bool:
    """Validate DNS identity from SAN, falling back to CN only without DNS SANs."""
    sans = certificate.get('subjectAltName', ()) or ()
    dns_names = [value for kind, value in sans if kind == 'DNS']
    if dns_names:
        return any(_dns_pattern_matches(name, hostname) for name in dns_names)

    common_names = []
    for group in certificate.get('subject', ()) or ():
        for key, value in group:
            if key == 'commonName':
                common_names.append(value)
    return any(_dns_pattern_matches(name, hostname) for name in common_names)


def certificate_validity(certificate: dict[str, Any], hostname: str,
                          observed_at: datetime | None = None) -> tuple[bool, list[str]]:
    """Evaluate certificate dates and hostname identity without external APIs."""
    observed_at = observed_at or datetime.now(timezone.utc)
    reasons = []
    not_before, not_after = _certificate_dates(certificate)
    if not not_before or not not_after:
        reasons.append('certificate validity dates unavailable')
    else:
        try:
            before = datetime.strptime(not_before, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
            after = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=timezone.utc)
            if observed_at < before:
                reasons.append('certificate not yet valid')
            if observed_at > after:
                reasons.append('certificate expired')
        except ValueError:
            reasons.append('certificate validity dates could not be parsed')

    if not _certificate_matches_hostname(certificate, hostname):
        reasons.append('hostname identity mismatch')

    return not reasons, reasons


def observe_hostname(hostname: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Make one passive TCP/TLS observation of a public HTTPS endpoint."""
    if not valid_hostname(hostname):
        raise ValueError(f'Invalid hostname: {hostname!r}')

    observed_at = utc_now()
    endpoint = f'{hostname}:443'
    result = {
        'hostname': hostname,
        'observation_type': 'tls',
        'observed_at': observed_at,
        'status': 'error',
        'validity': False,
        'issuer': None,
        'subject': None,
        'expiration': None,
        'valid_from': None,
        'sans': [],
        'protocol': None,
        'cipher': None,
        'certificate_sha256': None,
        'evidence': {
            'method': 'passive TLS handshake',
            'endpoint': endpoint,
            'port': DEFAULT_PORT,
            'user_agent': USER_AGENT,
            'verification_policy': 'system CA verification and hostname verification',
        },
    }

    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, DEFAULT_PORT), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as connection:
                der = connection.getpeercert(binary_form=True)
                certificate = connection.getpeercert()
                cipher = connection.cipher()
                protocol = connection.version()

                result.update({
                    'status': 'observed',
                    'validity': True,
                    'issuer': _issuer_string(certificate),
                    'subject': _subject_string(certificate),
                    'expiration': certificate.get('notAfter'),
                    'valid_from': certificate.get('notBefore'),
                    'sans': [
                        {'type': kind, 'value': value}
                        for kind, value in certificate.get('subjectAltName', ())
                    ],
                    'protocol': protocol,
                    'cipher': {
                        'name': cipher[0],
                        'protocol': cipher[1],
                        'secret_bits': cipher[2],
                    } if cipher else None,
                    'certificate_sha256': hashlib.sha256(der).hexdigest(),
                    'evidence': {
                        **result['evidence'],
                        'certificate_sha256': hashlib.sha256(der).hexdigest(),
                        'tls_protocol': protocol,
                    },
                })
    except (OSError, ssl.SSLError, ValueError, TimeoutError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        result['evidence']['error_type'] = type(exc).__name__

    return result


def _cache_path(cache_dir: str | Path, hostname: str) -> Path:
    digest = hashlib.sha256(hostname.encode('ascii')).hexdigest()
    return Path(cache_dir) / f'{digest}.json'


def collect_hostnames(hostnames: list[str], output: str | Path = DEFAULT_OUTPUT,
                      cache_dir: str | Path = DEFAULT_CACHE,
                      cache_max_age: int = DEFAULT_CACHE_AGE,
                      timeout: int = DEFAULT_TIMEOUT,
                      delay_seconds: float = 1.0) -> dict[str, Any]:
    """Collect observations, reuse fresh per-host caches, and persist progress."""
    normalized = sorted({h.lower().rstrip('.') for h in hostnames if valid_hostname(h)})
    if not normalized:
        raise ValueError('No valid hostnames supplied for TLS collection')

    destination = Path(output)
    cache = Path(cache_dir)
    existing: dict[str, dict[str, Any]] = {}
    if destination.exists():
        previous = load_json(destination)
        if isinstance(previous, dict) and isinstance(previous.get('observations'), list):
            existing = {
                item['hostname']: item
                for item in previous['observations']
                if isinstance(item, dict) and isinstance(item.get('hostname'), str)
            }

    observations = dict(existing)
    for hostname in normalized:
        cache_file = _cache_path(cache, hostname)
        record = None
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age <= cache_max_age:
                cached = load_json(cache_file)
                if isinstance(cached, dict) and cached.get('hostname') == hostname:
                    record = cached

        if record is None:
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            record = observe_hostname(hostname, timeout=timeout)
            write_json(cache_file, record)

        observations[hostname] = record
        # Persist after every host so interruption does not discard completed work.
        document = {
            'schema_version': SCHEMA_VERSION,
            'observation_type': 'tls',
            'source': 'passive public TLS handshake',
            'user_agent': USER_AGENT,
            'created_at': utc_now(),
            'requested_hostname_count': len(normalized),
            'completed_count': len([h for h in normalized if h in observations]),
            'observations': [observations[h] for h in sorted(observations)],
        }
        write_json(destination, document)

    return load_json(destination)


def collect_sample(sample_path: str | Path = DEFAULT_SAMPLE, **kwargs: Any) -> dict[str, Any]:
    sample = load_json(sample_path)
    if not isinstance(sample, dict) or not isinstance(sample.get('hostnames'), list):
        raise ValueError('TLS sample must contain a hostnames array')
    return collect_hostnames(sample['hostnames'], **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description='Passive TLS and certificate audit')
    subparsers = parser.add_subparsers(dest='command', required=True)

    sample_parser = subparsers.add_parser('sample')
    sample_parser.add_argument('--mapping', default=str(DEFAULT_MAPPING))
    sample_parser.add_argument('--ct-cache', default=str(DEFAULT_CT_CACHE))
    sample_parser.add_argument('--output', default=str(DEFAULT_SAMPLE))
    sample_parser.add_argument('--size', type=int, default=20)

    collect_parser = subparsers.add_parser('collect')
    collect_parser.add_argument('--sample', default=str(DEFAULT_SAMPLE))
    collect_parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    collect_parser.add_argument('--cache-dir', default=str(DEFAULT_CACHE))
    collect_parser.add_argument('--cache-age', type=int, default=DEFAULT_CACHE_AGE)
    collect_parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    collect_parser.add_argument('--delay', type=float, default=1.0)

    args = parser.parse_args()
    if args.command == 'sample':
        document = create_sample(args.output, args.mapping, args.ct_cache, args.size)
    else:
        document = collect_sample(
            args.sample,
            output=args.output,
            cache_dir=args.cache_dir,
            cache_max_age=args.cache_age,
            timeout=args.timeout,
            delay_seconds=args.delay,
        )
    print(json.dumps({
        'command': args.command,
        'hostname_count': document.get('sample_count', document.get('completed_count')),
        'output': args.output,
    }, indent=2))


if __name__ == '__main__':
    main()
