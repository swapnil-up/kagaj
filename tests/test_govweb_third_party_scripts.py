import json
import urllib.parse
from pathlib import Path

import pytest

from govweb import third_party_scripts as audit


def test_sample_only_accepts_discovered_gov_np_and_caps_at_twenty(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"hostnames": ["A.gov.np", "a.gov.np"]}), encoding="utf-8")
    assert audit.load_sample(sample) == ["a.gov.np"]
    sample.write_text(json.dumps({"hostnames": [f"h{i}.gov.np" for i in range(21)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)
    sample.write_text(json.dumps({"hostnames": ["example.com"]}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)


def test_url_normalization_resolves_relative_and_rejects_non_http():
    assert audit.normalize_url("/assets/app.js", "https://a.gov.np/") == "https://a.gov.np/assets/app.js"
    assert audit.normalize_url("//cdn.example/x.js", "https://a.gov.np/") == "https://cdn.example/x.js"
    assert audit.normalize_url("javascript:alert(1)", "https://a.gov.np/") is None


def test_script_extraction_deduplicates_and_ignores_inline_scripts():
    html = '<script src="/a.js"></script><script src="https://cdn.example/b.js"></script><script>run()</script><script src="/a.js"></script>'
    found = audit.extract_script_urls(html, "https://a.gov.np/")
    assert found == ["https://a.gov.np/a.js", "https://cdn.example/b.js"]


def test_first_party_includes_subdomains():
    result = audit.classify_script("https://static.a.gov.np/app.js", "a.gov.np")
    assert result["category"] == "first_party"
    assert result["confidence"] == "high"


@pytest.mark.parametrize("url,expected", [
    ("https://www.googletagmanager.com/gtm.js", "analytics"),
    ("https://googleads.g.doubleclick.net/pagead.js", "advertising"),
    ("https://cdnjs.cloudflare.com/ajax/libs/x.js", "cdn"),
    ("https://www.youtube.com/embed/x", "embedded"),
    ("https://unknown.example/x.js", "other"),
])
def test_external_script_classification(url, expected):
    assert audit.classify_script(url, "municipality.gov.np")["category"] == expected


def test_multiple_category_matches_are_conservatively_other():
    result = audit.classify_script("https://analytics.cloudflare.example/ads.js", "a.gov.np")
    assert result["category"] == "other"
    assert result["confidence"] == "low"


def test_robots_disallow_prevents_page_fetch(tmp_path):
    calls = []
    def fake_fetch(url, timeout=15):
        calls.append(url)
        if url.endswith("robots.txt"):
            return url, b"User-agent: *\nDisallow: /\n"
        raise AssertionError("page must not be fetched")
    result = audit.fetch_page("https://a.gov.np/", tmp_path, fetcher=fake_fetch)
    assert result["status"] == "robots_disallowed"
    assert calls == ["https://a.gov.np/robots.txt"]


def test_robots_unavailable_fails_closed(tmp_path):
    def fail_fetch(url, timeout=15):
        raise OSError("offline")
    result = audit.fetch_page("https://a.gov.np/", tmp_path, fetcher=fail_fetch)
    assert result["status"] == "robots_disallowed"
    assert "fail-closed" in result["evidence"][0]


def test_allowed_robots_then_fetches_html_and_extracts_scripts(tmp_path):
    calls = []
    def fake_fetch(url, timeout=15):
        calls.append(url)
        if url.endswith("robots.txt"):
            return url, b"User-agent: *\nAllow: /\n"
        return url, b'<html><script src="https://cdn.example/a.js"></script></html>'
    result = audit.fetch_page("https://a.gov.np/", tmp_path, fetcher=fake_fetch)
    assert result["status"] == "ok"
    assert result["scripts"] == ["https://cdn.example/a.js"]
    assert calls == ["https://a.gov.np/robots.txt", "https://a.gov.np/"]


def test_robots_cache_avoids_second_fetch(tmp_path):
    calls = []
    def fake_fetch(url, timeout=15):
        calls.append(url)
        return url, b"User-agent: *\nAllow: /\n"
    assert audit.robots_allowed("https://a.gov.np/", tmp_path, fetcher=fake_fetch)[0]
    assert audit.robots_allowed("https://a.gov.np/", tmp_path, fetcher=fake_fetch)[0]
    assert calls == ["https://a.gov.np/robots.txt"]


def test_observation_records_evidence_and_classification(tmp_path):
    def fake_fetch(url, timeout=15):
        if url.endswith("robots.txt"):
            return url, b"User-agent: *\nAllow: /\n"
        return url, b'<script src="https://www.googletagmanager.com/gtm.js"></script><script src="/local.js"></script>'
    observation = audit.observe_site("a.gov.np", tmp_path, fetcher=fake_fetch, delay=0)
    assert observation["observation_type"] == "third_party_script_inventory"
    assert observation["status"] == "ok"
    assert observation["script_count"] == 2
    assert observation["third_party_script_count"] == 1
    assert {item["category"] for item in observation["scripts"]} == {"analytics", "first_party"}
    assert observation["evidence"]


def test_observation_cache_reuses_successful_result(tmp_path):
    calls = []
    def fake_fetch(url, timeout=15):
        calls.append(url)
        if url.endswith("robots.txt"):
            return url, b"User-agent: *\nAllow: /\n"
        return url, b"<script src='/x.js'></script>"
    first = audit.observe_site("a.gov.np", tmp_path, fetcher=fake_fetch, delay=0)
    second = audit.observe_site("a.gov.np", tmp_path, fetcher=lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")), delay=0)
    assert first == second
    assert len(calls) == 2


def test_collection_writes_incremental_aggregate(tmp_path, monkeypatch):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"hostnames": ["a.gov.np", "b.gov.np"]}), encoding="utf-8")
    monkeypatch.setattr(audit, "observe_site", lambda hostname, **kwargs: {"site_hostname": hostname, "status": "robots_disallowed"})
    output = tmp_path / "out.json"
    audit.collect(sample, output, tmp_path / "cache", delay=0)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["requested_hostname_count"] == 2
    assert document["completed_count"] == 2
    assert [item["site_hostname"] for item in document["observations"]] == ["a.gov.np", "b.gov.np"]


def test_cache_expiration_and_atomic_write(tmp_path):
    path = tmp_path / "cache.json"
    audit.write_cache(path, {"answer": 42})
    assert audit.read_cache(path)["answer"] == 42
    assert not path.with_suffix(".json.tmp").exists()
    path.write_text(json.dumps({"cached_at": "2000-01-01T00:00:00Z", "value": 1}), encoding="utf-8")
    assert audit.read_cache(path, ttl_hours=1) is None
