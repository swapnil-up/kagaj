import gzip
import hashlib
import json
from pathlib import Path

import pytest

from govweb import build


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _dataset(root: Path) -> Path:
    dataset = root / "datasets" / "govweb"
    _write(dataset / "roster.json", [
        {
            "province_id": "1", "province": "Province One",
            "district_id": "11", "district": "District One",
            "municipality_id": "100", "name": "Example Municipality",
            "normalized_name": "example municipality",
        }
    ])
    _write(dataset / "tls_sample.json", {"hostnames": ["a.gov.np"]})
    _write(dataset / "website_mappings_crtsh.json", {"mappings": [
        {"municipality_id": "100", "municipality": "Example Municipality",
         "district": "District One", "province": "Province One",
         "domains": [], "status": "unresolved", "source_url": "https://crt.sh/"},
    ]})
    _write(dataset / "website_coverage_crtsh.json", {"roster_count": 1, "mapped_count": 0})
    _write(dataset / "sources" / "crtsh_gov_np.json", [
        {"name_value": "a.gov.np\nmail.a.gov.np", "common_name": "a.gov.np"},
    ])
    _write(dataset / "observations" / "http_header_observations.json", {"observations": [
        {"url": "https://a.gov.np/", "headers": {"Content-Security-Policy": "default-src 'self'"},
         "status": "observed", "timestamp": "2026-11-05T00:00:00Z"},
        {"url": "https://b.gov.np/", "headers": {}, "status": "error",
         "error": "timed out", "timestamp": "2026-11-05T00:00:01Z"},
    ]})
    _write(dataset / "observations" / "hosting_observations.json", {"observations": [
        {"hostname": "a.gov.np", "ip_addresses": ["1.2.3.4"], "asn": ["64500"],
         "organization": ["Example ISP"], "country": ["Nepal"], "country_codes": ["NP"],
         "hosting_classification": "Nepal-local", "confidence": "high",
         "status": "observed", "observed_at": "2026-11-05T00:00:00Z", "error": None},
    ]})
    _write(dataset / "observations" / "dns_mail_observations.json", {"observations": [
        {"site_hostname": "a.gov.np", "dns_records": {"A": ["1.2.3.4"], "MX": ["mx.a.gov.np"],
         "TXT": ["v=spf1 -all"]}, "dmarc_txt_records": ["v=DMARC1; p=reject"],
         "mail_security": {"mx_present": True, "spf": {"status": "enforced"},
         "dmarc": {"status": "reject", "policy": "reject"}},
         "status": "ok", "confidence": "high", "observed_at": "2026-11-05T00:00:00Z"},
    ]})
    _write(dataset / "observations" / "third_party_scripts.json", {"observations": [
        {"site_hostname": "a.gov.np", "status": "ok", "script_count": 1,
         "third_party_script_count": 1, "observed_at": "2026-11-05T00:00:00Z",
         "scripts": [{"url": "https://cdn.example/x.js", "hostname": "cdn.example",
         "category": "cdn", "confidence": "medium"}]},
    ]})
    _write(dataset / "observations" / "robots_observations.json", {"observations": [
        {"hostname": "a.gov.np", "accessible": True, "status_code": 200, "status": "success",
         "directives": [{"user_agents": ["*"], "directives": [{"directive": "disallow", "value": "/"}]}],
         "final_url": "https://a.gov.np/robots.txt", "error": None,
         "observed_at": "2026-11-05T00:00:00Z"},
    ]})
    return dataset


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    path = _dataset(root)
    monkeypatch.setattr(build, "DATASET_DIR", path)
    monkeypatch.setattr(build, "OBSERVATION_DIR", path / "observations")
    monkeypatch.setattr(build, "SOURCE_DIR", path / "sources")
    return path


def _rows(path: Path) -> list[list[str]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [line.rstrip("\n").split(",") for line in handle]


def test_sites_are_hostname_first_and_keep_subdomains(dataset):
    build.build()
    rows = _rows(dataset / "sites.csv.gz")
    assert rows[0] == ["hostname", "apex_hostname", "subdomain", "in_observed_sample", "discovered_via"]
    hosts = {row[0]: row for row in rows[1:]}
    assert hosts["a.gov.np"][1] == "a.gov.np"
    assert hosts["mail.a.gov.np"][1] == "a.gov.np"
    assert hosts["mail.a.gov.np"][2] == "mail"
    assert hosts["a.gov.np"][3] == "true"
    assert hosts["mail.a.gov.np"][3] == "false"


def test_header_table_preserves_failed_observations(dataset):
    build.build()
    rows = _rows(dataset / "http_headers.csv.gz")
    header = rows[0]
    by_host = {row[0]: dict(zip(header, row)) for row in rows[1:]}
    assert by_host["a.gov.np"]["has_content_security_policy"] == "true"
    assert by_host["a.gov.np"]["missing_header_count"] == "5"
    assert by_host["b.gov.np"]["status"] == "error"
    assert by_host["b.gov.np"]["missing_header_count"] == "6"


def test_unavailable_tls_still_produces_a_header_only_artifact(dataset):
    build.build()
    rows = _rows(dataset / "tls.csv.gz")
    assert len(rows) == 1
    assert rows[0][0] == "hostname"


def test_build_fingerprint_matches_files_on_disk(dataset):
    info = build.build()
    for name in ("sites.csv.gz", "roster.csv.gz", "attribution.csv.gz", "hosting.csv.gz"):
        path = dataset / name
        entry = info["files"][name]
        assert entry["bytes"] == path.stat().st_size
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["rows"] == len(_rows(path)) - 1
    on_disk = json.loads((dataset / "build.json").read_text(encoding="utf-8"))
    assert on_disk["files"] == info["files"]


def test_build_is_deterministic(dataset):
    first = build.build()
    second = build.build()
    assert first["files"] == second["files"]
