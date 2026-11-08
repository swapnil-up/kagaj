import json
from pathlib import Path

import pytest

from govweb import verify


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    path = tmp_path / "datasets" / "govweb"
    _write(path / "roster.json", [
        {
            "province_id": "1", "province": "Province One",
            "district_id": "11", "district": "District One",
            "municipality_id": "100", "name": "Example Metropolitan City",
            "normalized_name": "example metropolitan city",
        },
        {
            "province_id": "1", "province": "Province One",
            "district_id": "11", "district": "District One",
            "municipality_id": "101", "name": "Example Rural Municipality",
            "normalized_name": "example rural municipality",
        },
        {
            "province_id": "1", "province": "Province One",
            "district_id": "11", "district": "District One",
            "municipality_id": "102", "name": "Example Rural Municipality",
            "normalized_name": "example rural municipality",
        },
    ])
    _write(path / "website_coverage_crtsh.json", {
        "roster_count": 3, "mapped_count": 0, "unresolved_count": 3,
        "coverage_percent": 0.0, "matching_policy": "exact only",
    })
    _write(path / "tls_sample.json", {"hostnames": ["a.gov.np"]})
    _write(path / "website_mappings_crtsh.json", {"mappings": [
        {"municipality_id": "100", "domains": []},
        {"municipality_id": "101", "domains": []},
        {"municipality_id": "102", "domains": []},
    ]})
    _write(path / "sources" / "crtsh_gov_np.json", [{"name_value": "a.gov.np"}])
    _write(path / "observations" / "robots_observations.json", {"observations": [
        {"hostname": "a.gov.np", "status": "success", "accessible": True},
    ]})
    monkeypatch.setattr(verify, "DATASET_DIR", path)
    return path


def test_local_level_type_normalises_source_spelling():
    assert verify.local_level_type("Kathmandu Metropolitan City") == "metropolitan_city"
    assert verify.local_level_type("Lalitpur Sub-Metropolitan City") == "sub_metropolitan_city"
    assert verify.local_level_type("Budhanilkantha Municipality") == "municipality"
    assert verify.local_level_type("Sonama Rural Municiaplity") == "rural_municipality"
    assert verify.local_level_type("Somewhere") == "unclassified"


def test_verify_records_roster_delta_and_duplicates(dataset):
    report = verify.verify()
    roster = report["roster"]
    assert roster["records"] == 3
    assert roster["delta"] == 3 - 753
    assert roster["by_type"] == {"metropolitan_city": 1, "rural_municipality": 2}
    assert roster["duplicate_district_name"] == [
        {"district": "district one", "name": "example rural municipality", "count": 2}
    ]


def test_verify_reports_missing_datasets_rather_than_zero(dataset):
    report = verify.verify()
    assert report["observations"]["tls"]["available"] is False
    assert report["observations"]["robots"]["available"] is True
    assert report["observations"]["robots"]["completed"] == 1


def test_verify_fails_when_observation_is_outside_inventory(dataset):
    _write(dataset / "observations" / "hosting_observations.json", {"observations": [
        {"hostname": "undiscovered.gov.np", "status": "observed"},
    ]})
    report = verify.verify()
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["observations_stay_within_discovered_inventory"]["status"] == "fail"


def test_write_report_round_trips(dataset):
    path, report = verify.write_report()
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["report_type"] == "govweb_reconciliation"
    assert report["discovery"]["ct_hostname_count"] == 1
