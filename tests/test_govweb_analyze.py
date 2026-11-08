import json
from pathlib import Path

from govweb import analyze


def put_json(root: Path, relative: str, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def base_inputs(root: Path):
    put_json(root, "roster.json", [{"municipality_id": "1", "name": "Example Municipality"}])
    put_json(root, "website_coverage_crtsh.json", {
        "unique_hostname_count": 100,
        "mapped_count": 0,
        "unresolved_count": 765,
        "coverage_percent": 0.0,
    })
    put_json(root, "tls_sample.json", {"hostnames": ["a.gov.np", "b.gov.np"]})


def test_missing_tls_is_unavailable_and_not_scored(tmp_path):
    base_inputs(tmp_path)
    report = analyze.analyze(tmp_path)
    assert report["input_availability"]["tls"] == "missing"
    assert "tls" not in report["scoring"]["components"]
    assert report["scope"]["sample_count"] == 2
    assert report["scope"]["sample_is_population_census"] is False


def test_http_header_score_uses_only_usable_responses(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/http_header_observations.json", {"observations": [
        {"hostname": "a.gov.np", "headers": {"Content-Security-Policy": "default-src 'self'", "Strict-Transport-Security": "max-age=1"}},
        {"hostname": "b.gov.np", "headers": {}, "error": "DNS failure"},
    ]})
    report = analyze.analyze(tmp_path)
    summary = report["datasets"]["http_headers"]
    assert summary["evaluable_count"] == 1
    assert summary["error_or_unusable_count"] == 1
    assert summary["score_numerator"] == 2
    assert summary["score_denominator"] == 6
    assert summary["score"] == 33.33


def test_header_matching_is_case_insensitive(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/http_header_observations.json", {"observations": [
        {"hostname": "a.gov.np", "headers": {"content-security-policy": "default-src 'self'"}},
    ]})
    report = analyze.analyze(tmp_path)
    assert report["datasets"]["http_headers"]["present_counts"]["Content-Security-Policy"] == 1


def test_dns_mail_score_requires_both_spf_and_dmarc(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/dns_mail_observations.json", {"observations": [
        {"site_hostname": "a.gov.np", "dns_records": {"TXT": ["v=spf1 -all"]}, "dmarc_txt_records": ["v=DMARC1; p=reject"], "errors": []},
        {"site_hostname": "b.gov.np", "dns_records": {"TXT": ["v=spf1 ~all"]}, "dmarc_txt_records": [], "errors": []},
    ]})
    report = analyze.analyze(tmp_path)
    summary = report["datasets"]["dns_mail"]
    assert summary["both_present_count"] == 1
    assert summary["evaluable_host_count"] == 2
    assert summary["score"] == 50.0


def test_dns_query_error_is_unknown_not_absent(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/dns_mail_observations.json", {"observations": [
        {"site_hostname": "a.gov.np", "dns_records": {"TXT": []}, "dmarc_txt_records": [], "errors": ["TXT query error: timeout"]},
    ]})
    report = analyze.analyze(tmp_path)
    summary = report["datasets"]["dns_mail"]
    assert summary["spf"]["unknown"] == 1
    assert summary["dmarc"]["unknown"] == 1
    assert summary["score"] is None


def test_exact_hostname_join_only_and_unmapped_hosts_retained(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/hosting_observations.json", {"observations": [
        {"hostname": "a.gov.np", "hosting_classification": "unknown"},
        {"hostname": "not-in-sample.gov.np", "hosting_classification": "foreign-cloud"},
    ]})
    report = analyze.analyze(tmp_path)
    hosts = {item["hostname"]: item for item in report["hosts"]}
    assert "hosting" in hosts["a.gov.np"]
    assert "hosting" not in hosts["b.gov.np"]
    assert "not-in-sample.gov.np" in hosts
    assert report["scope"]["municipality_hostname_join_policy"].startswith("exact_normalized_hostname_only")


def test_dataset_counts_are_reported_without_turning_errors_into_success(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/robots_observations.json", {"observations": [
        {"hostname": "a.gov.np", "accessible": False, "status": "error", "error": "DNS failure"},
        {"hostname": "b.gov.np", "accessible": True, "status": "ok"},
    ]})
    put_json(tmp_path, "observations/third_party_scripts.json", {"observations": [
        {"site_hostname": "a.gov.np", "third_party_script_count": 0, "status": "error", "evidence": ["robots.txt unavailable"]},
        {"site_hostname": "b.gov.np", "third_party_script_count": 2, "status": "observed"},
    ]})
    report = analyze.analyze(tmp_path)
    robots = report["datasets"]["robots"]
    scripts = report["datasets"]["third_party_scripts"]
    assert robots["accessible_count"] == 1
    assert robots["inaccessible_or_unknown_count"] == 1
    assert scripts["third_party_script_total"] == 2
    assert scripts["hosts_with_third_party_scripts"] == 1


def test_invalid_json_is_reported_and_does_not_crash(tmp_path):
    base_inputs(tmp_path)
    path = tmp_path / "observations/http_header_observations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")
    report = analyze.analyze(tmp_path)
    assert report["input_availability"]["http_headers"] == "invalid"
    assert report["datasets"]["http_headers"]["observation_count"] == 0


def test_report_is_deterministic_and_markdown_explains_limitations(tmp_path):
    base_inputs(tmp_path)
    first = analyze.analyze(tmp_path)
    second = analyze.analyze(tmp_path)
    assert first == second
    markdown = analyze.render_markdown(first)
    assert "not a population census" in markdown
    assert "no TLS score is assigned" in markdown


def test_combined_score_averages_only_available_components(tmp_path):
    base_inputs(tmp_path)
    put_json(tmp_path, "observations/http_header_observations.json", {"observations": [
        {"hostname": "a.gov.np", "headers": {"Content-Security-Policy": "x"}},
    ]})
    put_json(tmp_path, "observations/dns_mail_observations.json", {"observations": [
        {"site_hostname": "a.gov.np", "dns_records": {"TXT": ["v=spf1 -all"]}, "dmarc_txt_records": ["v=DMARC1; p=reject"], "errors": []},
    ]})
    report = analyze.analyze(tmp_path)
    components = report["scoring"]["components"]
    assert components == {"http_headers": 16.67, "dns_mail": 100.0}
    assert report["scoring"]["combined_score"] == 58.34


def test_missing_optional_artifacts_do_not_block_analysis(tmp_path):
    base_inputs(tmp_path)
    report = analyze.analyze(tmp_path)
    assert report["input_availability"]["hosting"] == "missing"
    assert report["input_availability"]["robots"] == "missing"
    assert report["scoring"]["combined_score"] is None


def test_write_report_creates_both_outputs(tmp_path):
    base_inputs(tmp_path)
    json_path, markdown_path = analyze.write_report(tmp_path)
    assert json_path.is_file()
    assert markdown_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "passive_infrastructure_audit_analysis"
    assert "## Limitations" in markdown_path.read_text(encoding="utf-8")
