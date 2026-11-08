import argparse
import hashlib
import html.parser
import ipaddress
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_SAMPLE = paths.DATASET_DIR / "tls_sample.json"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "third_party_scripts.json"
DEFAULT_CACHE = paths.CACHE_DIR / "third_party_scripts"
DEFAULT_TIMEOUT = 15
DEFAULT_DELAY = 1.0
DEFAULT_CACHE_TTL_HOURS = 168
MAX_HTML_BYTES = 2_000_000
MAX_REDIRECTS = 5

CATEGORY_KEYWORDS = {
    "analytics": ("google-analytics", "googletagmanager", "gtag", "analytics", "matomo", "plausible", "hotjar", "clarity.ms", "mixpanel", "segment.io", "amplitude"),
    "advertising": ("doubleclick", "googlesyndication", "adsystem", "adservice", "adsbygoogle", "googleadservices", "facebook.com/tr", "pixel", "adroll", "taboola", "outbrain"),
    "cdn": ("cdnjs", "jsdelivr", "unpkg", "cloudflare", "cloudfront", "akamai", "fastly", "bootstrapcdn", "staticfile", "jquery.com"),
    "embedded": ("youtube", "youtu.be", "vimeo", "maps.google", "google.com/maps", "recaptcha", "hcaptcha", "twitter.com/widgets", "platform.twitter", "facebook.net", "linkedin.com"),
}


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
    with Path(path).open(encoding="utf-8") as handle:
        document = json.load(handle)
    values = document.get("hostnames")
    if not isinstance(values, list):
        raise ValueError("TLS sample must contain a hostnames list")
    result = sorted({normalize_hostname(item) for item in values})
    if len(result) > 20:
        raise ValueError("Script inventory is limited to the existing 20-host sample")
    return result


def normalize_url(value, base_url):
    absolute = urllib.parse.urljoin(base_url, value.strip())
    parsed = urllib.parse.urlsplit(absolute)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return None
    if parsed.username or parsed.password:
        return None
    return urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


def hostname_of(url):
    parsed = urllib.parse.urlsplit(url)
    return (parsed.hostname or "").lower().rstrip(".")


def is_same_site(host, site):
    host = host.lower().rstrip(".")
    site = site.lower().rstrip(".")
    return host == site or host.endswith("." + site)


class ScriptParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "script":
            return
        values = dict(attrs)
        src = values.get("src")
        if src:
            self.sources.append(src)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def extract_script_urls(html_text, page_url):
    parser = ScriptParser()
    parser.feed(html_text)
    parser.close()
    result = set()
    for source in parser.sources:
        normalized = normalize_url(source, page_url)
        if normalized:
            result.add(normalized)
    return sorted(result)


def classify_script(url, site_hostname):
    host = hostname_of(url)
    if not host:
        raise ValueError("Script URL has no hostname")
    if is_same_site(host, site_hostname):
        return {"category": "first_party", "confidence": "high", "evidence": ["script hostname matches the audited site"]}
    haystack = (host + urllib.parse.urlsplit(url).path).lower()
    matches = []
    for category in ("analytics", "advertising", "cdn", "embedded"):
        keywords = CATEGORY_KEYWORDS[category]
        found = [keyword for keyword in keywords if keyword in haystack]
        if found:
            matches.append((category, found))
    if len(matches) == 1:
        category, found = matches[0]
        return {"category": category, "confidence": "medium", "evidence": ["URL matched known category indicators: " + ", ".join(found)]}
    if len(matches) > 1:
        return {"category": "other", "confidence": "low", "evidence": ["URL matched multiple category indicators; classification left unresolved"]}
    return {"category": "other", "confidence": "low", "evidence": ["external script URL had no recognized category indicators"]}


def cache_key(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_cache(path, ttl_hours=DEFAULT_CACHE_TTL_HOURS):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(payload["cached_at"].replace("Z", "+00:00"))
        if utc_now() - observed > timedelta(hours=ttl_hours):
            return None
        return payload.get("value")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def write_cache(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"cached_at": timestamp(), "value": value}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_bytes(url, timeout=DEFAULT_TIMEOUT, max_bytes=MAX_HTML_BYTES):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type and content_type:
            raise ValueError("Response is not HTML")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("HTML response exceeds configured size limit")
    return final_url, body


def robots_allowed(page_url, cache_dir, timeout=DEFAULT_TIMEOUT, fetcher=request_bytes):
    parsed = urllib.parse.urlsplit(page_url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    cache_path = Path(cache_dir) / (cache_key(robots_url) + ".json")
    cached = read_cache(cache_path)
    if cached is not None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(cached.splitlines())
        return parser.can_fetch(USER_AGENT, page_url), "cached robots.txt"
    try:
        _, body = fetcher(robots_url, timeout=timeout)
        text = body.decode("utf-8", errors="replace")
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(text.splitlines())
        write_cache(cache_path, text)
        return parser.can_fetch(USER_AGENT, page_url), "robots.txt"
    except Exception as exc:
        # Fail closed: inability to verify robots policy means do not fetch the page.
        return False, "robots.txt unavailable; fail-closed: " + type(exc).__name__


def fetch_page(page_url, cache_dir, timeout=DEFAULT_TIMEOUT, fetcher=request_bytes):
    allowed, robots_evidence = robots_allowed(page_url, cache_dir, timeout, fetcher)
    if not allowed:
        return {"status": "robots_disallowed", "evidence": [robots_evidence], "final_url": page_url, "scripts": []}
    try:
        final_url, body = fetcher(page_url, timeout=timeout)
        text = body.decode("utf-8", errors="replace")
        scripts = extract_script_urls(text, final_url)
        return {"status": "ok", "evidence": [robots_evidence, "public HTML fetched with identifying User-Agent"], "final_url": final_url, "scripts": scripts}
    except Exception as exc:
        return {"status": "fetch_error", "evidence": [robots_evidence, type(exc).__name__ + ": " + str(exc)], "final_url": page_url, "scripts": []}


def observe_site(hostname, cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT, fetcher=request_bytes, delay=DEFAULT_DELAY):
    hostname = normalize_hostname(hostname)
    page_url = "https://" + hostname + "/"
    cache_path = Path(cache_dir) / (cache_key(page_url) + ".json")
    cached = read_cache(cache_path)
    if cached is not None:
        return cached
    result = fetch_page(page_url, cache_dir, timeout=timeout, fetcher=fetcher)
    scripts = []
    for script_url in result["scripts"]:
        classification = classify_script(script_url, hostname)
        scripts.append({"url": script_url, "hostname": hostname_of(script_url), **classification})
    observation = {
        "municipality_id": None,
        "site_hostname": hostname,
        "observation_type": "third_party_script_inventory",
        "observed_at": timestamp(),
        "source_url": result["final_url"],
        "status": result["status"],
        "scripts": scripts,
        "script_count": len(scripts),
        "third_party_script_count": sum(1 for item in scripts if item["category"] != "first_party"),
        "evidence": result["evidence"],
        "confidence": "high" if result["status"] == "ok" else "low"
    }
    write_cache(cache_path, observation)
    if delay > 0:
        time.sleep(delay)
    return observation


def collect(sample_path=DEFAULT_SAMPLE, output_path=DEFAULT_OUTPUT, cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT, delay=DEFAULT_DELAY):
    hostnames = load_sample(sample_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    for hostname in hostnames:
        observations.append(observe_site(hostname, cache_dir=cache_dir, timeout=timeout, delay=delay))
        document = {
            "observation_type": "third_party_script_inventory",
            "created_at": timestamp(),
            "requested_hostname_count": len(hostnames),
            "completed_count": len(observations),
            "observations": observations
        }
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(output_path)
    if not hostnames:
        output_path.write_text(json.dumps({"observation_type": "third_party_script_inventory", "created_at": timestamp(), "requested_hostname_count": 0, "completed_count": 0, "observations": []}, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Passive third-party script inventory for discovered .gov.np sites")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("collect")
    command.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    command.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    command.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    command.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    command.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)
    if args.command == "collect":
        path = collect(args.sample, args.out, args.cache, args.timeout, args.delay)
        print(path)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
