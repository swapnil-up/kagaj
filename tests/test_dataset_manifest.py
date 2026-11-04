"""Dataset descriptors: every dataset publishes a valid dataset.json, and the
generated datasets/index.json matches what the descriptors describe.
Contract: docs/dataset-manifest.md"""

import json

import pytest

from kagaj_core import manifest


def _valid_descriptor() -> dict:
    return {
        "schema_version": manifest.SCHEMA_VERSION,
        "id": "sample",
        "title": "Sample dataset",
        "status": "active",
        "description": "A dataset built in a temporary directory.",
        "grain": "one row per thing",
        "coverage": {"start": "2080 Baishakh", "end": "2081 Baishakh"},
        "sources": [{"name": "Example", "url": "https://example.com"}],
        "artifacts": [{"path": "data.csv", "role": "primary", "format": "csv"}],
        "verification": {"status": "none", "method": "none"},
        "docs": [],
        "license": {"code": "MIT", "data": "MIT"},
    }


@pytest.fixture()
def sample_dataset(tmp_path):
    dataset_dir = tmp_path / "sample"
    dataset_dir.mkdir()
    (dataset_dir / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _write(dataset_dir, _valid_descriptor())
    return dataset_dir


def _write(dataset_dir, doc):
    (dataset_dir / manifest.DESCRIPTOR_NAME).write_text(
        json.dumps(doc, indent=2), encoding="utf-8"
    )


def test_every_dataset_has_an_error_free_descriptor():
    issues = manifest.validate_all()
    errors = [issue for issue in issues if issue.level == "error"]
    assert not errors, "\n".join(str(issue) for issue in errors)


def test_discover_finds_the_shipped_datasets():
    ids = {path.name for path in manifest.discover()}
    assert {"crime", "labour-migration", "translations", "water"} <= ids


def test_warnings_are_the_documented_ones():
    warnings = [issue for issue in manifest.validate_all() if issue.level == "warning"]
    known = {"freshness", "artifacts"}
    unexpected = [issue for issue in warnings if issue.field not in known]
    assert not unexpected, "\n".join(str(issue) for issue in unexpected)


def test_committed_index_is_current():
    expected = json.dumps(manifest.build_index(), ensure_ascii=False, indent=2) + "\n"
    committed = manifest.INDEX_PATH.read_text(encoding="utf-8")
    assert committed == expected, (
        "datasets/index.json is stale — run: python -m kagaj_core.manifest index"
    )


def test_index_has_one_primary_artifact_per_dataset():
    for dataset in manifest.build_index()["datasets"]:
        primary = [a for a in dataset["artifacts"] if a["role"] == "primary"]
        assert len(primary) == 1, dataset["id"]
        assert primary[0]["path"], dataset["id"]


def test_index_records_fingerprints_and_columns():
    index = {d["id"]: d for d in manifest.build_index()["datasets"]}
    crime = index["crime"]
    assert crime["freshness"]["fingerprints"] == ["build.json"]
    assert crime["freshness"]["commit"]
    primary = next(a for a in crime["artifacts"] if a["role"] == "primary")
    assert "month" in primary["columns"]
    assert primary["sha256"]

    migration = index["labour-migration"]
    canonical = next(a for a in migration["artifacts"] if a["role"] == "primary")
    assert canonical["rows"] == 70089

    assert index["translations"]["artifacts"][0]["file_count"] > 200


def test_rejects_wrong_schema_version(sample_dataset):
    doc = _valid_descriptor()
    doc["schema_version"] = "0.9"
    _write(sample_dataset, doc)
    errors = [i for i in manifest.validate(sample_dataset) if i.level == "error"]
    assert any(i.field == "schema_version" for i in errors)


def test_rejects_id_that_does_not_match_directory(sample_dataset):
    doc = _valid_descriptor()
    doc["id"] = "something-else"
    _write(sample_dataset, doc)
    errors = [i for i in manifest.validate(sample_dataset) if i.level == "error"]
    assert any(i.field == "id" for i in errors)


def test_rejects_unknown_role_and_missing_file(sample_dataset):
    doc = _valid_descriptor()
    doc["artifacts"][0]["role"] = "headline"
    doc["artifacts"].append({"path": "absent.csv", "role": "raw", "format": "csv"})
    _write(sample_dataset, doc)
    fields = {i.field for i in manifest.validate(sample_dataset) if i.level == "error"}
    assert any(f.startswith("artifacts[0].role") for f in fields)
    assert any(f.startswith("artifacts[1].path") for f in fields)


def test_requires_exactly_one_primary_artifact(sample_dataset):
    doc = _valid_descriptor()
    doc["artifacts"][0]["role"] = "raw"
    _write(sample_dataset, doc)
    errors = [i for i in manifest.validate(sample_dataset) if i.level == "error"]
    assert any(i.field == "artifacts" and "primary" in i.message for i in errors)


def test_rejects_path_escaping_the_dataset(sample_dataset):
    doc = _valid_descriptor()
    doc["artifacts"][0]["path"] = "../elsewhere.csv"
    _write(sample_dataset, doc)
    errors = [i for i in manifest.validate(sample_dataset) if i.level == "error"]
    assert any(i.field.startswith("artifacts[0].path") for i in errors)


def test_pattern_artifacts_must_match_at_least_one_file(sample_dataset):
    doc = _valid_descriptor()
    doc["artifacts"].append(
        {"path": ".", "pattern": "*.parquet", "role": "reference", "format": "json"}
    )
    _write(sample_dataset, doc)
    errors = [i for i in manifest.validate(sample_dataset) if i.level == "error"]
    assert any("no files match" in i.message for i in errors)
