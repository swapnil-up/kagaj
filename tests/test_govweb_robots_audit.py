import hashlib
import json
import urllib.error

import pytest

from govweb import robots_audit as audit


class FakeResponse:
    def __init__(self, body=b"User-agent: *\nDisallow: /private\nAllow: /public\n", status=200,
                 url="https://example.gov.np/robots.txt"):
        self.body = body
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body[:size]

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url


def test_normalize_hostname_accepts_only_gov_np():
    assert audit.normalize_hostname("Example.GOV.NP.") == "example.gov.np"
    with pytest.raises(ValueError):
        audit.normalize_hostname("example.com")
    with pytest.raises(ValueError):
        audit.normalize_hostname("https://example.gov.np")


@pytest.mark.parametrize("hostname", [
    "-bad.gov.np", "bad-.gov.np", "bad..gov.np", "bad_name.gov.np",
    "bad label.gov.np", "*.gov.np", "bad\\name.gov.np",
])
def test_normalize_hostname_rejects_invalid_dns_labels(hostname):
    with pytest.raises(ValueError):
        audit.normalize_hostname(hostname)


def test_normalize_hostname_supports_idna():
    assert audit.normalize_hostname("münchen.gov.np") == "xn--mnchen-3ya.gov.np"


def test_load_sample_deduplicates_and_limits(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"hostnames": ["a.gov.np", "A.gov.np", "b.gov.np"]}), encoding="utf-8")
    assert audit.load_sample(sample) == ["a.gov.np", "b.gov.np"]
    sample.write_text(json.dumps({"hostnames": [f"h{i}.gov.np" for i in range(21)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)


def test_load_sample_rejects_missing_or_invalid_hostnames(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"other": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)
    sample.write_text(json.dumps({"hostnames": "example.gov.np"}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)


def test_parse_robots_groups_and_directives():
    parsed = audit.parse_robots("""# comment
User-agent: *
Disallow: /private # private
Allow: /public
Crawl-delay: 5
Sitemap: https://example.gov.np/sitemap.xml

User-agent: Googlebot
Disallow: /secret
""")
    assert parsed == [
        {
            "user_agents": ["*"],
            "directives": [
                {"directive": "disallow", "value": "/private"},
                {"directive": "allow", "value": "/public"},
                {"directive": "crawl-delay", "value": "5"},
                {"directive": "sitemap", "value": "https://example.gov.np/sitemap.xml"},
            ],
        },
        {
            "user_agents": ["Googlebot"],
            "directives": [{"directive": "disallow", "value": "/secret"}],
        },
    ]


def test_parse_robots_groups_consecutive_user_agents():
    assert audit.parse_robots("User-agent: BotA\nUser-agent: BotB\nDisallow: /x\n") == [
        {"user_agents": ["BotA", "BotB"], "directives": [{"directive": "disallow", "value": "/x"}]}
    ]


def test_parse_robots_empty_disallow_is_preserved():
    assert audit.parse_robots("User-agent: *\nDisallow:\n") == [
        {"user_agents": ["*"], "directives": [{"directive": "disallow", "value": ""}]}
    ]


def test_fetch_robots_records_raw_evidence_and_headers():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["timeout"] = timeout
        return FakeResponse(url=request.full_url)

    result = audit.fetch_robots("example.gov.np", opener=opener, timeout=7)
    assert result["accessible"] is True
    assert result["status_code"] == 200
    assert result["status"] == "success"
    assert result["directives"][0]["directives"][0] == {"directive": "disallow", "value": "/private"}
    assert result["evidence"]["content"].startswith("User-agent: *")
    assert result["evidence"]["content_sha256"] == hashlib.sha256(FakeResponse().body).hexdigest()
    assert result["evidence"]["content_bytes"] == len(FakeResponse().body)
    assert captured["url"] == "https://example.gov.np/robots.txt"
    assert captured["headers"]["User-agent"] == audit.USER_AGENT
    assert captured["timeout"] == 7


@pytest.mark.parametrize("status", [301, 403, 404, 500])
def test_fetch_robots_non_200_is_unavailable(status):
    result = audit.fetch_robots(
        "example.gov.np",
        opener=lambda request, timeout: FakeResponse(status=status, url=request.full_url),
    )
    assert result["accessible"] is False
    assert result["status_code"] == status
    assert result["status"] == "unavailable"
    assert result["directives"] == []


def test_fetch_robots_http_error_is_recorded():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    result = audit.fetch_robots("example.gov.np", opener=opener)
    assert result["status_code"] == 403
    assert result["status"] == "unavailable"


@pytest.mark.parametrize("redirect_url", [
    "https://other.gov.np/robots.txt",
    "http://example.gov.np/robots.txt",
    "https://example.gov.np:444/robots.txt",
    "https://user@example.gov.np/robots.txt",
])
def test_fetch_robots_rejects_unsafe_redirects(redirect_url):
    result = audit.fetch_robots(
        "example.gov.np",
        opener=lambda request, timeout: FakeResponse(url=redirect_url),
    )
    assert result["status"] == "error"
    assert result["evidence"]["redirect_rejected"] is True
    assert result["confidence"] == "low"


def test_fetch_robots_accepts_same_host_default_https_port():
    result = audit.fetch_robots(
        "example.gov.np",
        opener=lambda request, timeout: FakeResponse(url="https://EXAMPLE.gov.np:443/robots.txt"),
    )
    assert result["status"] == "success"


def test_fetch_robots_rejects_oversized_body():
    body = b"x" * (audit.MAX_ROBOTS_BYTES + 1)
    with pytest.raises(ValueError):
        audit.fetch_robots("example.gov.np", opener=lambda request, timeout: FakeResponse(body=body, url=request.full_url))


def test_cache_round_trip_and_expiry(tmp_path):
    path = tmp_path / "cache.json"
    audit.write_cache(path, {"status": "success"})
    assert audit.read_cache(path) == {"status": "success"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cached_at"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert audit.read_cache(path) is None


def test_cache_rejects_future_and_naive_timestamps(tmp_path):
    path = tmp_path / "cache.json"
    for cached_at in ("2999-01-01T00:00:00Z", "2020-01-01T00:00:00"):
        path.write_text(json.dumps({"cached_at": cached_at, "value": {"status": "success"}}), encoding="utf-8")
        assert audit.read_cache(path) is None


def test_observe_host_uses_success_cache_without_fetch(tmp_path):
    cache = tmp_path / "cache"
    first = audit.observe_host("example.gov.np", cache_dir=cache, opener=lambda request, timeout: FakeResponse(url=request.full_url), delay=0)
    second = audit.observe_host(
        "example.gov.np",
        cache_dir=cache,
        opener=lambda request, timeout: (_ for _ in ()).throw(AssertionError("network should not be called")),
        delay=0,
    )
    assert first == second


def test_observe_host_retries_cached_error(tmp_path):
    cache = tmp_path / "cache"
    audit.write_cache(cache / (audit.cache_key("example.gov.np") + ".json"), {"status": "error"})
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(url=request.full_url)

    result = audit.observe_host("example.gov.np", cache_dir=cache, opener=opener, delay=0)
    assert result["status"] == "success"
    assert calls == ["https://example.gov.np/robots.txt"]


def test_observe_host_records_network_error(tmp_path):
    def opener(request, timeout):
        raise OSError("offline")

    result = audit.observe_host("example.gov.np", cache_dir=tmp_path, opener=opener, delay=0)
    assert result["status"] == "error"
    assert result["confidence"] == "low"
    assert result["evidence"]["error"] == "OSError"


def test_collect_resumes_and_writes_aggregate_after_each_host(tmp_path):
    output = tmp_path / "robots.json"
    cache = tmp_path / "cache"
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(url=request.full_url)

    result = audit.collect(["a.gov.np", "b.gov.np"], output=output, cache_dir=cache, delay=0, opener=opener)
    assert len(result) == 2
    assert len(calls) == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["observation_type"] == "robots"
    assert saved["completed_count"] == 2
    audit.collect(
        ["a.gov.np", "b.gov.np"],
        output=output,
        cache_dir=cache,
        delay=0,
        opener=lambda request, timeout: (_ for _ in ()).throw(AssertionError("completed hosts should not be fetched")),
    )


def test_collect_retries_prior_error_observation(tmp_path):
    output = tmp_path / "robots.json"
    output.write_text(json.dumps({"observations": [{"hostname": "a.gov.np", "status": "error"}]}), encoding="utf-8")
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse(url=request.full_url)

    result = audit.collect(["a.gov.np"], output=output, cache_dir=tmp_path / "cache", delay=0, opener=opener)
    assert result[0]["status"] == "success"
    assert calls == ["https://a.gov.np/robots.txt"]


def test_collect_ignores_prior_hosts_outside_sample(tmp_path):
    output = tmp_path / "robots.json"
    output.write_text(json.dumps({"observations": [{"hostname": "outside.gov.np", "status": "success"}]}), encoding="utf-8")
    result = audit.collect(
        ["inside.gov.np"], output=output, cache_dir=tmp_path / "cache", delay=0,
        opener=lambda request, timeout: FakeResponse(url=request.full_url),
    )
    assert [item["hostname"] for item in result] == ["inside.gov.np"]


def test_collect_deduplicates_and_enforces_sample_limit(tmp_path):
    result = audit.collect(
        ["a.gov.np", "A.gov.np"], output=tmp_path / "out.json",
        cache_dir=tmp_path / "cache", delay=0,
        opener=lambda request, timeout: FakeResponse(url=request.full_url),
    )
    assert [item["hostname"] for item in result] == ["a.gov.np"]
    with pytest.raises(ValueError):
        audit.collect([f"h{i}.gov.np" for i in range(21)], output=tmp_path / "other.json")


def test_rate_limit_sleeps_between_requests(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(audit.time, "monotonic", lambda: 10.5)
    last = [10.0]
    audit.observe_host(
        "example.gov.np", cache_dir=tmp_path,
        opener=lambda request, timeout: FakeResponse(url=request.full_url),
        delay=1, sleeper=sleeps.append, last_request=last,
    )
    assert sleeps == [pytest.approx(0.5)]
    assert last == [10.5]


def test_output_is_atomically_replaced(tmp_path):
    output = tmp_path / "out.json"
    document = audit.write_output(output, [{"hostname": "a.gov.np", "status": "success"}])
    assert output.exists()
    assert not output.with_suffix(".json.tmp").exists()
    assert document["completed_count"] == 1


def test_only_robots_resource_is_requested():
    captured = []
    audit.fetch_robots(
        "example.gov.np",
        opener=lambda request, timeout: (captured.append(request.full_url) or FakeResponse(url=request.full_url)),
    )
    assert captured == ["https://example.gov.np/robots.txt"]
