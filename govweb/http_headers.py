import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_TIMEOUT = 12
DEFAULT_DELAY = 1.0
DEFAULT_CACHE_TTL_HOURS = 168
DEFAULT_SAMPLE = paths.DATASET_DIR / "tls_sample.json"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "http_header_observations.json"
DEFAULT_CACHE = paths.CACHE_DIR / "http_headers"

REQUIRED_SECURITY_HEADERS = {
    "Content-Security-Policy": "A restrictive policy appropriate to the website",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY or SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "Explicitly restrict unnecessary browser capabilities"
}


def utc_now():
    return datetime.now(timezone.utc)


def iso_timestamp(value=None):
    value = value or utc_now()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_url(url):
    url = str(url).strip()
    if not url:
        raise ValueError("URL cannot be empty")
    if "://" not in url:
        url = "https://" + url
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS URLs are accepted")
    return url.rstrip("/") + "/"


def fetch_http_headers(url, timeout=DEFAULT_TIMEOUT, user_agent=USER_AGENT):
    """Fetch root-resource response headers without consuming the response body."""
    url = normalize_url(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.8"},
        method="GET"
    )
    timestamp = utc_now()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return dict(response.headers.items()), timestamp, response.status, response.geturl()
    except urllib.error.HTTPError as exc:
        # HTTP error responses are still valid header observations.
        return dict(exc.headers.items()) if exc.headers else {}, timestamp, exc.code, exc.geturl()


def audit_http_headers(headers):
    """Return security headers absent from a case-insensitive header mapping."""
    normalized = {str(key).lower(): value for key, value in headers.items()}
    return {
        name: recommendation
        for name, recommendation in REQUIRED_SECURITY_HEADERS.items()
        if name.lower() not in normalized
    }


def collect_http_headers_for_sites(sites, timeout=DEFAULT_TIMEOUT,
                                   delay=0.0, user_agent=USER_AGENT,
                                   fetcher=None):
    """Collect one root-response header observation per supplied URL.

    Network errors are retained as observations rather than silently dropped.
    The function is injectable for deterministic offline testing.
    """
    fetcher = fetcher or fetch_http_headers
    results = []
    for index, site in enumerate(sites):
        url = normalize_url(site)
        observed_at = utc_now()
        try:
            headers, timestamp, status, final_url = fetcher(
                url, timeout=timeout, user_agent=user_agent
            )
            headers = dict(headers or {})
            results.append({
                "url": url,
                "final_url": final_url,
                "headers": headers,
                "response_status": status,
                "missing_security_headers": audit_http_headers(headers),
                "timestamp": iso_timestamp(timestamp),
                "status": "observed",
                "error": None
            })
        except Exception as exc:
            results.append({
                "url": url,
                "final_url": None,
                "headers": {},
                "response_status": None,
                "missing_security_headers": audit_http_headers({}),
                "timestamp": iso_timestamp(observed_at),
                "status": "error",
                "error": "{}: {}".format(type(exc).__name__, str(exc))
            })
        if delay > 0 and index < len(sites) - 1:
            time.sleep(delay)
    return results


def load_sample(path=DEFAULT_SAMPLE):
    """Load only actual discovered hostnames from the TLS sample."""
    sample_path = Path(path)
    if not sample_path.is_file():
        raise FileNotFoundError("TLS sample not found: {}".format(sample_path))
    with sample_path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    hostnames = document.get("hostnames")
    if not isinstance(hostnames, list):
        raise ValueError("TLS sample must contain a hostnames list")
    result = []
    seen = set()
    for hostname in hostnames:
        hostname = str(hostname).strip().lower().rstrip(".")
        if not hostname or hostname in seen:
            continue
        if "/" in hostname or ":" in hostname or "*" in hostname:
            continue
        if not hostname.endswith(".gov.np"):
            continue
        seen.add(hostname)
        result.append("https://" + hostname + "/")
    return sorted(result)


def cache_path(url, cache_dir=DEFAULT_CACHE):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(cache_dir) / (digest + ".json")


def read_cache(url, cache_dir=DEFAULT_CACHE, ttl_hours=DEFAULT_CACHE_TTL_HOURS):
    path = cache_path(url, cache_dir)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            record = json.load(handle)
        observed = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        if utc_now() - observed > timedelta(hours=ttl_hours):
            return None
        if record.get("url") != url:
            return None
        return record
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def atomic_write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def collect(sample_path=DEFAULT_SAMPLE, output_path=DEFAULT_OUTPUT,
            cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT,
            delay=DEFAULT_DELAY, ttl_hours=DEFAULT_CACHE_TTL_HOURS,
            user_agent=USER_AGENT):
    """Collect, cache, and incrementally persist observations for the TLS sample."""
    urls = load_sample(sample_path)
    cache_dir = Path(cache_dir)
    output_path = Path(output_path)

    existing = {}
    if output_path.is_file():
        try:
            with output_path.open(encoding="utf-8") as handle:
                old_document = json.load(handle)
            for item in old_document.get("observations", []):
                if item.get("url"):
                    existing[item["url"]] = item
        except (OSError, ValueError, TypeError):
            existing = {}

    observations = []
    collected_count = 0
    for url in urls:
        record = read_cache(url, cache_dir, ttl_hours)
        if record is None:
            record = collect_http_headers_for_sites(
                [url], timeout=timeout, delay=0, user_agent=user_agent
            )[0]
            atomic_write_json(cache_path(url, cache_dir), record)
            collected_count += 1
            # Persist every completed hostname for interruption recovery.
            existing[url] = record
            document = build_document(urls, existing, user_agent)
            atomic_write_json(output_path, document)
            if delay > 0 and url != urls[-1]:
                time.sleep(delay)
        else:
            existing[url] = record
        observations.append(record)

    document = build_document(urls, existing, user_agent)
    atomic_write_json(output_path, document)
    print("HTTP header observations: {}".format(len(observations)))
    print("New network observations: {}".format(collected_count))
    print("Output: {}".format(output_path))
    return document


def build_document(urls, records, user_agent=USER_AGENT):
    observations = [records[url] for url in urls if url in records]
    return {
        "schema_version": 1,
        "observation_type": "http_security_headers",
        "source": "Discovered hostnames from data/tls_sample.json",
        "user_agent": user_agent,
        "created_at": iso_timestamp(),
        "requested_url_count": len(urls),
        "completed_count": len(observations),
        "observations": observations
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Passive HTTP security-header audit of discovered HTTPS sites"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="Collect HTTP response headers")
    collect_parser.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    collect_parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    collect_parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    collect_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    collect_parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    collect_parser.add_argument("--cache-ttl-hours", type=float, default=DEFAULT_CACHE_TTL_HOURS)
    collect_parser.add_argument("--user-agent", default=USER_AGENT)

    args = parser.parse_args(argv)
    if args.command == "collect":
        try:
            collect(
                sample_path=args.sample,
                output_path=args.out,
                cache_dir=args.cache_dir,
                timeout=args.timeout,
                delay=args.delay,
                ttl_hours=args.cache_ttl_hours,
                user_agent=args.user_agent
            )
            return 0
        except Exception as exc:
            print("Collection failed: {}".format(exc), file=sys.stderr)
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
