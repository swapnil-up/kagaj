"""Tests for hashes and build manifests."""

from kagaj_core.provenance import (
    artifact_manifest,
    build_manifest,
    require_clean,
    sha256_bytes,
    verify_manifest,
)


def test_sha256_bytes_matches_known_digest():
    assert sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_build_manifest_and_verify(tmp_path):
    (tmp_path / "a.csv").write_text("x\n1\n")
    (tmp_path / "b.csv").write_text("y\n2\n")
    manifest = build_manifest(["a.csv", "b.csv"], tmp_path,
                              generated_at="2026-10-30T00:00:00+0000",
                              extra={"rows": 2})
    assert manifest["generated_at"] == "2026-10-30T00:00:00+0000"
    assert manifest["rows"] == 2
    assert set(manifest["files"]) == {"a.csv", "b.csv"}
    assert verify_manifest(manifest, tmp_path) == []


def test_verify_manifest_reports_missing_and_tampered(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("x\n")
    manifest = {"files": artifact_manifest([path], tmp_path)}
    assert verify_manifest(manifest, tmp_path) == []

    path.write_text("changed\n")
    assert any("sha256" in problem for problem in
               verify_manifest(manifest, tmp_path))

    path.unlink()
    assert any("missing" in problem for problem in
               verify_manifest(manifest, tmp_path))


def test_require_clean_checks_git_metadata():
    assert require_clean({"git": {"commit": "abc", "dirty": False}}) == []
    assert require_clean({"git": {"commit": "abc", "dirty": True}})
    assert require_clean({"git": {"commit": "", "dirty": False}})
