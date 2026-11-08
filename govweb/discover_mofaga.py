"""Discover local-level websites from the MoFAGA public directory.

This path is opportunistic: the ministry site is frequently unreachable, and
collection stops rather than guessing when robots policy cannot be verified.
Certificate Transparency remains the primary discovery source.
"""

from __future__ import annotations

import hashlib
import json
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from . import paths
from .website_discovery import build_coverage, map_roster, parse_directory_html

SOURCE = "https://mofaga.gov.np/local-contact"
USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
CACHE = paths.CACHE_DIR / "mofaga_local_contact"


class _NextLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        rel = (attrs.get("rel") or "").casefold().split()
        if tag == "a" and "next" in rel and attrs.get("href"):
            self.href = attrs["href"]


def _fetch(url, cache_path=None):
    if cache_path is not None and cache_path.exists():
        return cache_path.read_bytes()
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:
        body = response.read()
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(body)
    return body


def _cache_path_for(url, suffix):
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return CACHE / f"{suffix}-{digest}.txt"


def _robots_allow(source):
    parsed = urlparse(source)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        robots_body = _fetch(robots_url, _cache_path_for(robots_url, "robots"))
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(robots_body.decode("utf-8", errors="replace").splitlines())
        return parser.can_fetch(USER_AGENT, source)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        return False


def _flatten_roster(data):
    """Accept the canonical flat roster or the OAG province/district nesting."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ValueError("Canonical roster must be a JSON object or list")

    for key in ("municipalities", "local_levels", "records", "roster"):
        value = data.get(key)
        if isinstance(value, list):
            return value

    provinces = data.get("provinces")
    if not isinstance(provinces, list):
        raise ValueError("Unrecognized canonical roster structure")

    flattened = []
    for province in provinces:
        province_id = province.get("province_id", province.get("id", ""))
        province_name = province.get("province", province.get("name", ""))
        for district in province.get("districts", []):
            district_id = district.get("district_id", district.get("id", ""))
            district_name = district.get("district", district.get("name", ""))
            municipalities = district.get("municipalities", district.get("local_levels", []))
            for municipality in municipalities:
                item = dict(municipality)
                item.setdefault("province_id", province_id)
                item.setdefault("province", province_name)
                item.setdefault("district_id", district_id)
                item.setdefault("district", district_name)
                flattened.append(item)
    if not flattened:
        raise ValueError("Canonical nested roster contains no municipality records")
    return flattened


def discover_websites(source=SOURCE, roster_path=None):
    """Fetch public directory pages only after robots approval; cache each page."""
    if not _robots_allow(source):
        raise RuntimeError("robots.txt is unavailable or disallows collection; refusing to fetch directory")

    roster_file = Path(roster_path) if roster_path else paths.DATASET_DIR / "roster.json"
    roster = _flatten_roster(json.loads(roster_file.read_text(encoding="utf-8")))

    all_rows = []
    next_url = source
    seen = set()
    page_count = 0

    while next_url and next_url not in seen:
        if page_count >= 100:
            raise RuntimeError("Directory pagination exceeded 100 pages")
        seen.add(next_url)
        page_cache = _cache_path_for(next_url, "page").with_suffix(".html")
        if not page_cache.exists() and page_count > 0:
            time.sleep(1.0)
        html = _fetch(next_url, page_cache).decode("utf-8", errors="replace")
        all_rows.extend(parse_directory_html(html, next_url))

        next_parser = _NextLinkParser()
        next_parser.feed(html)
        next_parser.close()
        next_url = urljoin(next_url, next_parser.href) if next_parser.href else None
        page_count += 1

    if not all_rows:
        raise RuntimeError("Directory produced no usable rows; refusing to write empty discovery output")

    mappings = map_roster(roster, all_rows, source)
    coverage = build_coverage(roster, mappings)
    paths.DATASET_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "mofaga_directory.json": {
            "source_url": source,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "page_count": page_count,
            "rows": all_rows,
        },
        "website_mappings_mofaga.json": mappings,
        "website_coverage_mofaga.json": coverage,
    }
    for filename, payload in outputs.items():
        (paths.DATASET_DIR / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return mappings, coverage
