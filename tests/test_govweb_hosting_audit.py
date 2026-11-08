import json
import socket
from datetime import datetime, timezone

import pytest

from govweb import hosting_audit as audit


def test_load_sample_uses_only_discovered_hosts(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({
        "hostnames": ["b.gov.np", "a.gov.np", "b.gov.np"]
    }), encoding="utf-8")
    assert audit.load_sample(path) == ["a.gov.np", "b.gov.np"]


def test_load_sample_rejects_more_than_twenty_hosts(tmp_path):
    path = tmp_path / "sample.json"
    path.write_text(json.dumps({
        "hostnames": ["h{}.gov.np".format(i) for i in range(21)]
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(path)


def test_hostname_normalization_and_restrictions():
    assert audit.normalize_hostname("WWW.GOV.NP.") == "www.gov.np"
    with pytest.raises(ValueError):
        audit.normalize_hostname("example.com")
    with pytest.raises(ValueError):
        audit.normalize_hostname("https://example.gov.np")


def test_resolve_hostname_returns_unique_sorted_addresses():
    def resolver(host, port, family, socktype):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:4860:4860::8888", 443, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        ]
    assert audit.resolve_hostname("example.gov.np", resolver) == ["8.8.8.8", "2001:4860:4860::8888"]


def test_classification_nepal_local():
    result, confidence = audit.classify_host(
        ["103.1.2.3"],
        {"103.1.2.3": {"country_code": "NP", "organization": "Nepal ISP"}}
    )
    assert result == "Nepal-local"
    assert confidence == "high"


def test_classification_foreign_cloud():
    result, confidence = audit.classify_host(
        ["8.8.8.8"],
        {"8.8.8.8": {"country_code": "US", "organization": "Google LLC"}}
    )
    assert result == "foreign-cloud"
    assert confidence == "high"


def test_classification_foreign_other():
    result, confidence = audit.classify_host(
        ["1.1.1.1"],
        {"1.1.1.1": {"country_code": "US", "organization": "Example Network"}}
    )
    assert result == "foreign-other"
    assert confidence == "high"


def test_classification_unknown_for_missing_or_conflicting_evidence():
    assert audit.classify_host([], {}) == ("unknown", "low")
    assert audit.classify_host(
        ["8.8.8.8"], {}
    ) == ("unknown", "low")
    assert audit.classify_host(
        ["8.8.8.8", "1.1.1.1"],
        {
            "8.8.8.8": {"country_code": "US", "organization": "Google"},
            "1.1.1.1": {"country_code": "AU", "organization": "Example"}
        }
    ) == ("unknown", "medium")


def test_private_ip_is_never_sent_to_geolocation(monkeypatch):
    with pytest.raises(ValueError):
        audit.fetch_geolocation("192.168.1.1")


def test_observe_host_records_dns_and_metadata_evidence(tmp_path):
    def resolver(hostname):
        return ["8.8.8.8"]

    def geolocator(address, timeout, user_agent):
        return {
            "ip_address": address,
            "asn": "AS15169",
            "organization": "Google LLC",
            "country": "United States",
            "country_code": "US",
            "provider": "ipwho.is",
            "source_url": "https://ipwho.is/8.8.8.8",
            "observed_at": audit.timestamp()
        }

    result = audit.observe_host(
        "example.gov.np", tmp_path, 5, 168, 0,
        resolver=resolver, geolocator=geolocator
    )
    assert result["ip_addresses"] == ["8.8.8.8"]
    assert result["asn"] == ["AS15169"]
    assert result["hosting_classification"] == "foreign-cloud"
    assert result["evidence"]["geolocation_provider"] == "ipwho.is"


def test_observe_host_reuses_host_cache(tmp_path):
    calls = []

    def resolver(hostname):
        calls.append(hostname)
        return ["8.8.8.8"]

    def geolocator(address, timeout, user_agent):
        return {
            "ip_address": address,
            "asn": "AS15169",
            "organization": "Google LLC",
            "country": "United States",
            "country_code": "US",
            "source_url": "https://ipwho.is/8.8.8.8"
        }

    first = audit.observe_host("example.gov.np", tmp_path, 5, 168, 0, resolver, geolocator)
    second = audit.observe_host("example.gov.np", tmp_path, 5, 168, 0, resolver, geolocator)
    assert first == second
    assert len(calls) == 1


def test_collection_writes_incremental_output(tmp_path):
    sample = tmp_path / "sample.json"
    output = tmp_path / "hosting.json"
    sample.write_text(json.dumps({"hostnames": ["one.gov.np", "two.gov.np"]}), encoding="utf-8")

    def resolver(hostname):
        return ["8.8.8.8"]

    def geolocator(address, timeout, user_agent):
        return {
            "ip_address": address,
            "asn": "AS15169",
            "organization": "Google LLC",
            "country": "United States",
            "country_code": "US",
            "source_url": "https://ipwho.is/8.8.8.8"
        }

    document = audit.collect(
        sample_path=sample,
        output_path=output,
        cache_dir=tmp_path / "cache",
        delay=0,
        resolver=resolver,
        geolocator=geolocator
    )
    assert output.is_file()
    assert document["completed_count"] == 2
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["completed_count"] == 2
    assert len(saved["observations"]) == 2


def test_dns_failure_is_retained_as_unknown():
    result = audit.observe_host(
        "example.gov.np",
        "/tmp/dinfra-hosting-test-cache-do-not-use",
        5, 168, 0,
        resolver=lambda hostname: [],
        geolocator=lambda *args, **kwargs: None
    )
    assert result["status"] == "error"
    assert result["hosting_classification"] == "unknown"
    assert result["ip_addresses"] == []
