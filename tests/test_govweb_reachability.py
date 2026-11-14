from __future__ import annotations

import socket

import pytest

from govweb import globalping, ip_registry, reachability_audit as r


def test_normalize_hostname_accepts_gov_np_and_rejects_others():
    assert r.normalize_hostname("Kathmandu.GOV.NP.") == "kathmandu.gov.np"
    with pytest.raises(ValueError):
        r.normalize_hostname("example.com")
    with pytest.raises(ValueError):
        r.normalize_hostname("a/b.gov.np")


def test_resolve_hostname_deduplicates_and_drops_scoped_ids():
    def resolver(host, port, family, kind):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("103.69.124.140", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("103.69.124.140", 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 0)),
        ]

    assert r.resolve_hostname("x.gov.np", resolver=resolver) == ["103.69.124.140", "fe80::1"]


def test_resolve_hostname_returns_empty_on_failure():
    def resolver(*_args):
        raise socket.gaierror("nope")

    assert r.resolve_hostname("dead.gov.np", resolver=resolver) == []


def test_tcp_probe_reports_open_against_a_local_listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        state = r.tcp_probe("127.0.0.1", port, timeout=2)
    finally:
        server.close()
    assert state["state"] == "open"
    assert state["port"] == port


def test_tcp_probe_reports_refused_on_a_closed_port():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.close()
    assert r.tcp_probe("127.0.0.1", port, timeout=2)["state"] in {"refused", "error"}


def test_collect_writes_hostname_and_address_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(r, "resolve_hostname", lambda host: ["203.0.113.9"])
    monkeypatch.setattr(r, "reverse_dns", lambda address: "ptr.example")
    monkeypatch.setattr(r, "tcp_probe", lambda address, port, timeout: {"port": port, "state": "open", "ms": 1})
    document = r.collect(["a.gov.np", "b.gov.np"], tmp_path / "out.json", ports=(80, 443))
    assert document["requested_hostname_count"] == 2
    assert document["address_count"] == 1
    assert document["addresses"][0]["ptr"] == "ptr.example"
    assert len(document["addresses"][0]["tcp"]) == 2
    assert (tmp_path / "out.json").is_file()


def test_rdap_network_summarizes_address_range():
    assert ip_registry._network("103.69.124.0", "103.69.127.255") == "103.69.124.0/22"
    assert ip_registry._network(None, None) is None


def test_rdap_lookup_rejects_invalid_address():
    record = ip_registry.lookup("not-an-address")
    assert record["status"] == "error"
    assert record["error"] == "invalid_address"


def test_globalping_normalize_records_probe_and_timing():
    document = {
        "target": "kathmandu.gov.np",
        "type": "http",
        "results": [
            {
                "probe": {"location": {"country": "NP", "city": "Kathmandu", "asn": 45424, "network": "Himalayan"}},
                "result": {"statusCode": 307, "resolvedAddress": "103.69.124.56", "timings": {"tcp": 12, "tls": 8, "total": 30}},
            }
        ],
    }
    records = globalping.normalize(document, "NP")
    assert len(records) == 1
    record = records[0]
    assert record["asn"] == 45424
    assert record["status_code"] == 307
    assert record["tcp_ms"] == 12


def test_globalping_normalize_falls_back_to_requested_country():
    document = {"target": "x.gov.np", "type": "http", "results": [{"probe": {}, "result": {}}]}
    assert globalping.normalize(document, "IN")[0]["country"] == "IN"


def test_rdap_collect_retries_until_observed(monkeypatch):
    calls = {"n": 0}

    def flaky(address, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"address": address, "status": "error", "error": "HTTPError"}
        return {"address": address, "status": "observed", "name": "DOITGON-NP"}

    monkeypatch.setattr(ip_registry, "lookup", flaky)
    monkeypatch.setattr(ip_registry.time, "sleep", lambda _seconds: None)
    document = ip_registry.collect(["103.69.124.140"], "/tmp/opencode/rdap_test.json", attempts=3)
    assert document["observed_address_count"] == 1
    assert calls["n"] == 3


def test_build_reachability_emits_a_row_for_unresolved_hostnames(monkeypatch):
    from govweb import build

    monkeypatch.setattr(
        build,
        "_load_reachability",
        lambda: {
            "hostnames": [
                {"hostname": "dead.gov.np", "dns_status": "no_answer", "addresses": [], "observed_at": "t"},
                {"hostname": "alive.gov.np", "dns_status": "ok", "addresses": ["203.0.113.5"], "observed_at": "t"},
            ],
            "addresses": [{"address": "203.0.113.5", "ptr": "p", "tcp": [{"port": 443, "state": "open", "ms": 3}]}],
        },
    )
    captured = {}

    def capture(path, header, rows):
        captured["rows"] = list(rows)
        return {"rows": len(captured["rows"])}

    monkeypatch.setattr(build, "write_csv_gz", capture)
    build.build_reachability()
    by_host = {row[0]: row for row in captured["rows"]}
    assert set(by_host) == {"dead.gov.np", "alive.gov.np"}
    assert by_host["dead.gov.np"][3] == "no_answer"
    assert by_host["dead.gov.np"][4] == ""
    assert by_host["alive.gov.np"][4] == ""
    assert by_host["alive.gov.np"][5] == "open"
