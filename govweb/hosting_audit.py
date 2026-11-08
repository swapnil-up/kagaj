import argparse
import hashlib
import ipaddress
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_SAMPLE = paths.DATASET_DIR / "tls_sample.json"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "hosting_observations.json"
DEFAULT_CACHE = paths.CACHE_DIR / "hosting"
DEFAULT_TIMEOUT = 12
DEFAULT_DELAY = 1.0
DEFAULT_CACHE_TTL_HOURS = 168
GEOLOCATION_ENDPOINT = "https://ipwho.is/"

CLOUD_KEYWORDS = (
    "amazon", "aws", "google cloud", "microsoft azure", "azure",
    "cloudflare", "digitalocean", "linode", "akamai", "oracle cloud",
    "vultr", "hetzner", "ovh", "alibaba cloud", "fastly",
    "amazon technologies", "google llc", "microsoft corporation"
)


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_hostname(value):
    value = str(value).strip().lower().rstrip(".")
    if not value or "/" in value or ":" in value or "*" in value:
        raise ValueError("Invalid hostname")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid IDNA hostname") from exc
    if not value.endswith(".gov.np"):
        raise ValueError("Only discovered .gov.np hostnames are accepted")
    return value


def load_sample(path=DEFAULT_SAMPLE):
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    hostnames = document.get("hostnames")
    if not isinstance(hostnames, list):
        raise ValueError("TLS sample must contain a hostnames list")
    result = sorted({normalize_hostname(host) for host in hostnames})
    if len(result) > 20:
        raise ValueError("Hosting audit is limited to the existing 20-host sample")
    return result


def resolve_hostname(hostname, resolver=None):
    """Resolve ordinary A/AAAA records using the system DNS resolver."""
    hostname = normalize_hostname(hostname)
    resolver = resolver or socket.getaddrinfo
    addresses = set()
    try:
        answers = resolver(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for answer in answers:
            address = answer[4][0].split("%", 1)[0]
            try:
                addresses.add(str(ipaddress.ip_address(address)))
            except ValueError:
                continue
    except (OSError, socket.gaierror):
        pass
    return sorted(addresses, key=lambda item: (ipaddress.ip_address(item).version, int(ipaddress.ip_address(item))))


def fetch_geolocation(address, timeout=DEFAULT_TIMEOUT, user_agent=USER_AGENT):
    """Fetch public IP registration/ASN/country metadata from ipwho.is."""
    parsed = ipaddress.ip_address(address)
    if not parsed.is_global:
        raise ValueError("Refusing public geolocation lookup for a non-global IP")
    url = GEOLOCATION_ENDPOINT + urllib.parse.quote(str(parsed), safe="")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Geolocation provider returned an unsuccessful result")
    connection = payload.get("connection") or {}
    return {
        "ip_address": str(parsed),
        "asn": connection.get("asn"),
        "organization": connection.get("org") or connection.get("isp"),
        "country": payload.get("country"),
        "country_code": payload.get("country_code"),
        "provider": "ipwho.is",
        "source_url": url,
        "observed_at": timestamp()
    }


def classify_host(addresses, metadata):
    """Classify conservatively using country and disclosed organization evidence."""
    if not addresses:
        return "unknown", "low"

    public_addresses = []
    for address in addresses:
        try:
            if ipaddress.ip_address(address).is_global:
                public_addresses.append(address)
        except ValueError:
            continue

    if not public_addresses:
        return "unknown", "low"

    known = [metadata[ip] for ip in public_addresses if ip in metadata]
    if len(known) != len(public_addresses):
        return "unknown", "low"

    countries = {str(item.get("country_code") or "").upper() for item in known}
    if not countries or "" in countries:
        return "unknown", "low"

    if len(countries) > 1:
        return "unknown", "medium"

    country = next(iter(countries))
    if country == "NP":
        return "Nepal-local", "high"

    organizations = " ".join(
        str(item.get("organization") or "").lower() for item in known
    )
    if any(keyword in organizations for keyword in CLOUD_KEYWORDS):
        return "foreign-cloud", "high"

    return "foreign-other", "high"


def cache_filename(key, directory):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Path(directory) / (digest + ".json")


def atomic_write(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def read_cache(key, directory, ttl_hours=DEFAULT_CACHE_TTL_HOURS):
    path = cache_filename(key, directory)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            record = json.load(handle)
        observed = datetime.fromisoformat(record["cache_timestamp"].replace("Z", "+00:00"))
        if utc_now() - observed > timedelta(hours=ttl_hours):
            return None
        if record.get("cache_key") != key:
            return None
        return record.get("value")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def write_cache(key, value, directory):
    atomic_write(cache_filename(key, directory), {
        "cache_key": key,
        "cache_timestamp": timestamp(),
        "value": value
    })


def observe_host(hostname, cache_dir, timeout, ttl_hours, delay,
                 resolver=None, geolocator=None):
    hostname = normalize_hostname(hostname)
    host_key = "host:" + hostname
    cached = read_cache(host_key, cache_dir, ttl_hours)
    if cached is not None:
        return cached

    resolver = resolver or resolve_hostname
    geolocator = geolocator or fetch_geolocation
    addresses = resolver(hostname)
    metadata = {}
    errors = []
    source_records = []

    for index, address in enumerate(addresses):
        try:
            parsed = ipaddress.ip_address(address)
            if not parsed.is_global:
                errors.append({"ip_address": address, "error": "Non-global address; enrichment skipped"})
                continue
            ip_key = "ip:" + str(parsed)
            result = read_cache(ip_key, cache_dir, ttl_hours)
            if result is None:
                try:
                    result = geolocator(str(parsed), timeout=timeout, user_agent=USER_AGENT)
                    write_cache(ip_key, result, cache_dir)
                    if delay > 0 and index < len(addresses) - 1:
                        time.sleep(delay)
                except Exception as exc:
                    errors.append({"ip_address": address, "error": str(exc)})
                    continue
            metadata[str(parsed)] = result
            source_records.append(result.get("source_url"))
        except ValueError as exc:
            errors.append({"ip_address": address, "error": str(exc)})

    classification, confidence = classify_host(addresses, metadata)
    countries = sorted({
        item.get("country") for item in metadata.values() if item.get("country")
    })
    country_codes = sorted({
        item.get("country_code") for item in metadata.values() if item.get("country_code")
    })
    asns = sorted({
        str(item.get("asn")) for item in metadata.values() if item.get("asn") is not None
    })
    organizations = sorted({
        item.get("organization") for item in metadata.values() if item.get("organization")
    })

    record = {
        "hostname": hostname,
        "observation_type": "hosting",
        "observed_at": timestamp(),
        "status": "observed" if addresses else "error",
        "ip_addresses": addresses,
        "asn": asns,
        "organization": organizations,
        "country": countries,
        "country_codes": country_codes,
        "hosting_classification": classification,
        "confidence": confidence,
        "evidence": {
            "dns_method": "system resolver getaddrinfo AF_UNSPEC",
            "geolocation_provider": "ipwho.is",
            "geolocation_source_urls": sorted(set(source_records)),
            "ip_metadata": metadata,
            "errors": errors,
            "user_agent": USER_AGENT
        },
        "error": "DNS returned no addresses" if not addresses else None
    }
    write_cache(host_key, record, cache_dir)
    return record


def build_document(hostnames, observations):
    return {
        "schema_version": 1,
        "observation_type": "hosting_classification",
        "source": "Discovered hostnames from data/tls_sample.json",
        "user_agent": USER_AGENT,
        "created_at": timestamp(),
        "requested_hostname_count": len(hostnames),
        "completed_count": len(observations),
        "observations": observations
    }


def collect(sample_path=DEFAULT_SAMPLE, output_path=DEFAULT_OUTPUT,
            cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT,
            delay=DEFAULT_DELAY, ttl_hours=DEFAULT_CACHE_TTL_HOURS,
            resolver=None, geolocator=None):
    hostnames = load_sample(sample_path)
    output_path = Path(output_path)
    cache_dir = Path(cache_dir)
    existing = {}

    if output_path.is_file():
        try:
            with output_path.open(encoding="utf-8") as handle:
                old = json.load(handle)
            for item in old.get("observations", []):
                if item.get("hostname"):
                    existing[item["hostname"]] = item
        except (OSError, ValueError, TypeError):
            existing = {}

    observations = []
    for hostname in hostnames:
        record = observe_host(
            hostname, cache_dir, timeout, ttl_hours, delay,
            resolver=resolver, geolocator=geolocator
        )
        existing[hostname] = record
        observations = [existing[name] for name in hostnames if name in existing]
        atomic_write(output_path, build_document(hostnames, observations))

    document = build_document(hostnames, observations)
    atomic_write(output_path, document)
    print("Hosting observations: {}".format(len(observations)))
    print("Output: {}".format(output_path))
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description="Passive hosting and ASN audit")
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("collect")
    command.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    command.add_argument("--out", default=str(DEFAULT_OUTPUT))
    command.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    command.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    command.add_argument("--cache-ttl-hours", type=float, default=DEFAULT_CACHE_TTL_HOURS)
    args = parser.parse_args(argv)
    try:
        collect(
            sample_path=args.sample,
            output_path=args.out,
            cache_dir=args.cache_dir,
            timeout=args.timeout,
            delay=args.delay,
            ttl_hours=args.cache_ttl_hours
        )
        return 0
    except Exception as exc:
        print("Hosting collection failed: {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
