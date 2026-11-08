import json
from datetime import datetime, timezone

import pytest

from govweb import http_headers


def fake_fetch(url, timeout, user_agent):
    return (
        {
            "Content-Type": "text/html",
            "X-Content-Type-Options": "nosniff",
            "Strict-Transport-Security": "max-age=31536000"
        },
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        200,
        url
    )


def test_audit_headers_is_case_insensitive():
    missing = http_headers.audit_http_headers({
        "content-security-policy": "default-src 'self'",
        "STRICT-TRANSPORT-SECURITY": "max-age=31536000",
        "x-content-type-options": "nosniff"
    })
    assert "Content-Security-Policy" not in missing
    assert "Strict-Transport-Security" not in missing
    assert "X-Content-Type-Options" not in missing
    assert "X-Frame-Options" in missing
    assert "Referrer-Policy" in missing
    assert "Permissions-Policy" in missing


def test_collect_http_headers_for_sites():
    sites = [
        "https://example.com",
        "https://example.org",
        "https://example.net"
    ]
    results = http_headers.collect_http_headers_for_sites(
        sites, fetcher=fake_fetch
    )
    assert len(results) == len(sites)
    for result in results:
        assert "url" in result
        assert "headers" in result
        assert "missing_security_headers" in result
        assert "timestamp" in result
        assert result["status"] == "observed"
        assert result["response_status"] == 200


def test_http_failure_is_retained(monkeypatch):
    def failing_fetch(url, timeout, user_agent):
        raise TimeoutError("connection timed out")

    results = http_headers.collect_http_headers_for_sites(
        ["https://example.com"], fetcher=failing_fetch
    )
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["response_status"] is None
    assert results[0]["headers"] == {}
    assert "timed out" in results[0]["error"]


def test_http_error_response_is_still_an_observation(monkeypatch):
    def error_response(url, timeout, user_agent):
        return ({"Content-Type": "text/html"}, datetime.now(timezone.utc), 403, url)

    results = http_headers.collect_http_headers_for_sites(
        ["https://example.com"], fetcher=error_response
    )
    assert results[0]["status"] == "observed"
    assert results[0]["response_status"] == 403
    assert "Content-Type" in results[0]["headers"]


def test_only_https_urls_are_accepted():
    with pytest.raises(ValueError):
        http_headers.normalize_url("http://example.com")


def test_sample_uses_actual_discovered_hostnames(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({
        "hostnames": [
            "b.gov.np",
            "a.gov.np",
            "b.gov.np",
            "not-a-government-domain.com",
            "*.invalid.gov.np"
        ]
    }), encoding="utf-8")
    assert http_headers.load_sample(sample) == [
        "https://a.gov.np/",
        "https://b.gov.np/"
    ]


def test_cache_reuses_fresh_observation(tmp_path):
    url = "https://example.gov.np/"
    record = {
        "url": url,
        "timestamp": http_headers.iso_timestamp(),
        "status": "observed",
        "headers": {"X-Content-Type-Options": "nosniff"}
    }
    path = http_headers.cache_path(url, tmp_path)
    http_headers.atomic_write_json(path, record)
    assert http_headers.read_cache(url, tmp_path, 168) == record


def test_cache_rejects_expired_observation(tmp_path):
    url = "https://example.gov.np/"
    record = {
        "url": url,
        "timestamp": "2020-01-01T00:00:00Z",
        "status": "observed"
    }
    http_headers.atomic_write_json(http_headers.cache_path(url, tmp_path), record)
    assert http_headers.read_cache(url, tmp_path, 168) is None


def test_collection_writes_incremental_aggregate_and_cache(tmp_path):
    sample = tmp_path / "sample.json"
    output = tmp_path / "observations.json"
    cache = tmp_path / "cache"
    sample.write_text(json.dumps({
        "hostnames": ["one.gov.np", "two.gov.np"]
    }), encoding="utf-8")

    calls = []

    def fetch(url, timeout, user_agent):
        calls.append(url)
        return ({"X-Content-Type-Options": "nosniff"},
                datetime.now(timezone.utc), 200, url)

    original = http_headers.fetch_http_headers
    http_headers.fetch_http_headers = fetch
    try:
        document = http_headers.collect(
            sample_path=sample,
            output_path=output,
            cache_dir=cache,
            delay=0
        )
    finally:
        http_headers.fetch_http_headers = original

    assert len(calls) == 2
    assert document["completed_count"] == 2
    assert output.is_file()
    assert len(list(cache.glob("*.json"))) == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert len(saved["observations"]) == 2


def test_collection_reuses_cache_without_network(tmp_path):
    sample = tmp_path / "sample.json"
    output = tmp_path / "observations.json"
    cache = tmp_path / "cache"
    sample.write_text(json.dumps({"hostnames": ["one.gov.np"]}), encoding="utf-8")
    url = "https://one.gov.np/"
    http_headers.atomic_write_json(
        http_headers.cache_path(url, cache),
        {
            "url": url,
            "timestamp": http_headers.iso_timestamp(),
            "status": "observed",
            "headers": {},
            "missing_security_headers": http_headers.audit_http_headers({}),
            "response_status": 200,
            "final_url": url,
            "error": None
        }
    )

    def unexpected_network(*args, **kwargs):
        raise AssertionError("Fresh cache should prevent network access")

    original = http_headers.fetch_http_headers
    http_headers.fetch_http_headers = unexpected_network
    try:
        result = http_headers.collect(
            sample_path=sample,
            output_path=output,
            cache_dir=cache,
            delay=0
        )
    finally:
        http_headers.fetch_http_headers = original
    assert result["completed_count"] == 1
    assert output.is_file()
