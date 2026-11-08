import json
from datetime import datetime, timezone, timedelta

import pytest

from govweb import dns_mail_audit as audit


def test_sample_accepts_only_discovered_gov_np_and_caps_at_twenty(tmp_path):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"hostnames": ["A.gov.np", "a.gov.np"]}), encoding="utf-8")
    assert audit.load_sample(sample) == ["a.gov.np"]
    sample.write_text(json.dumps({"hostnames": [f"h{i}.gov.np" for i in range(21)]}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)
    sample.write_text(json.dumps({"hostnames": ["example.com"]}), encoding="utf-8")
    with pytest.raises(ValueError):
        audit.load_sample(sample)


def test_spf_missing_and_multiple_records():
    assert audit.evaluate_spf([])["status"] == "missing"
    result = audit.evaluate_spf(["v=spf1 -all", "v=spf1 ~all"])
    assert result["status"] == "multiple_records"


@pytest.mark.parametrize("record,status,qualifier", [
    ("v=spf1 include:_spf.example -all", "enforced", "-"),
    ("v=spf1 include:_spf.example ~all", "softfail", "~"),
    ("v=spf1 ?all", "neutral", "?"),
    ("v=spf1 +all", "permissive", "+"),
    ("v=spf1 include:example", "missing_all", None),
])
def test_spf_all_qualifier_evaluation(record, status, qualifier):
    result = audit.evaluate_spf([record])
    assert result["status"] == status
    assert result["all_qualifier"] == qualifier


def test_spf_record_matching_is_case_insensitive():
    assert audit.evaluate_spf(["V=SPF1 -all"])["status"] == "enforced"


def test_dmarc_missing_and_multiple_records():
    assert audit.evaluate_dmarc([])["status"] == "missing"
    assert audit.evaluate_dmarc(["v=DMARC1; p=none", "v=DMARC1; p=reject"])["status"] == "multiple_records"


@pytest.mark.parametrize("record,status,policy", [
    ("v=DMARC1; p=none; rua=mailto:dmarc@example.org", "monitoring", "none"),
    ("v=DMARC1; p=quarantine; sp=reject", "quarantine", "quarantine"),
    ("v=DMARC1; p=reject; pct=100", "reject", "reject"),
    ("v=DMARC1", "invalid", None),
    ("v=DMARC1; p=invalid", "invalid", "invalid"),
])
def test_dmarc_policy_evaluation(record, status, policy):
    result = audit.evaluate_dmarc([record])
    assert result["status"] == status
    assert result["policy"] == policy


def test_dmarc_tags_are_parsed():
    result = audit.evaluate_dmarc(["v=DMARC1; p=reject; sp=quarantine; rua=mailto:a@example.org"])
    assert result["tags"]["rua"] == "mailto:a@example.org"
    assert result["subdomain_policy"] == "quarantine"


def test_dns_query_uses_doh_and_parses_requested_type():
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps({"Status": 0, "Answer": [{"type": 16, "data": '"v=spf1 -all"'}, {"type": 1, "data": "192.0.2.1"}]}).encode()
    captured = {}
    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        return Response()
    records, evidence = audit.query_dns("a.gov.np", "TXT", opener=opener)
    assert records == ['"v=spf1 -all"']
    assert "cloudflare-dns.com" in captured["url"]
    assert evidence["query_type"] == "TXT"
    assert "User-agent" in captured["headers"]


def test_query_rejects_unsupported_type():
    with pytest.raises(ValueError):
        audit.query_dns("a.gov.np", "PTR")


def test_collection_caches_records_and_records_failures(tmp_path):
    calls = []
    def queryer(name, record_type, timeout=15):
        calls.append((name, record_type))
        if record_type == "MX":
            raise OSError("lookup failed")
        if name.startswith("_dmarc."):
            return ["v=DMARC1; p=reject"], {"query_name": name, "query_type": record_type}
        if record_type == "TXT":
            return ["v=spf1 -all"], {"query_name": name, "query_type": record_type}
        return [], {"query_name": name, "query_type": record_type}
    records, dmarc, evidence, errors = audit.collect_record_set("a.gov.np", tmp_path, queryer=queryer, delay=0)
    assert records["TXT"] == ["v=spf1 -all"]
    assert dmarc == ["v=DMARC1; p=reject"]
    assert errors[0]["record_type"] == "MX"
    count = len(calls)
    audit.collect_record_set("a.gov.np", tmp_path, queryer=lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache miss")), delay=0)
    assert len(calls) == count


def test_observation_evaluates_mail_security_and_marks_partial(tmp_path):
    def queryer(name, record_type, timeout=15):
        if name.startswith("_dmarc."):
            return ["v=DMARC1; p=quarantine"], {"query_name": name}
        if record_type == "TXT":
            return ["v=spf1 -all"], {"query_name": name}
        if record_type == "MX":
            raise OSError("temporary error")
        return [], {"query_name": name}
    result = audit.observe_host("a.gov.np", tmp_path, queryer=queryer, delay=0)
    assert result["status"] == "partial"
    assert result["mail_security"]["spf"]["status"] == "enforced"
    assert result["mail_security"]["dmarc"]["status"] == "quarantine"
    assert result["mail_security"]["mx_present"] is False
    assert result["errors"]


def test_atomic_cache_and_expiry(tmp_path):
    path = tmp_path / "entry.json"
    audit.write_cache(path, {"ok": True})
    assert audit.read_cache(path)["ok"] is True
    assert not path.with_suffix(".json.tmp").exists()
    path.write_text(json.dumps({"cached_at": "2000-01-01T00:00:00Z", "value": 1}), encoding="utf-8")
    assert audit.read_cache(path, ttl_hours=1) is None


def test_aggregate_output_is_incremental_and_complete(tmp_path, monkeypatch):
    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"hostnames": ["a.gov.np", "b.gov.np"]}), encoding="utf-8")
    monkeypatch.setattr(audit, "observe_host", lambda hostname, *args, **kwargs: {"site_hostname": hostname, "status": "ok"})
    output = tmp_path / "observations.json"
    audit.collect(sample, output, tmp_path / "cache", delay=0)
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["requested_hostname_count"] == 2
    assert document["completed_count"] == 2
    assert len(document["observations"]) == 2


def test_dns_name_is_derived_only_for_dmarc():
    assert audit.normalize_hostname("Example.gov.np") == "example.gov.np"
    with pytest.raises(ValueError):
        audit.normalize_hostname("_dmarc.example.gov.np")
