from pathlib import Path

import pytest

from cidmap.reference_fonts import (
    ReferenceFontError,
    reference_dirs,
    resolve_reference_font,
    resolve_reference_fonts,
)


def test_resolves_alias_from_local_directory(tmp_path, monkeypatch):
    font = tmp_path / "Kokila.ttf"
    font.write_bytes(b"")
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    assert resolve_reference_font("kokila") == font


def test_resolves_nested_file_and_normalized_name(tmp_path, monkeypatch):
    font = tmp_path / "legacy" / "Fontasy Himali TT.ttf"
    font.parent.mkdir()
    font.write_bytes(b"")
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    assert resolve_reference_font("fontasy himali") == font


def test_existing_path_wins(tmp_path, monkeypatch):
    font = tmp_path / "Kalimati.ttf"
    font.write_bytes(b"")
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path / "missing"))
    assert resolve_reference_font(font) == font


def test_unknown_alias_reports_available_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    with pytest.raises(ReferenceFontError, match="kokila"):
        resolve_reference_font("not-a-font")


def test_missing_path_does_not_fall_back_to_alias(tmp_path, monkeypatch):
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    with pytest.raises(ReferenceFontError, match="not found"):
        resolve_reference_font(tmp_path / "missing.ttf")


def test_partial_alias_and_unknown_suffix_fail_closed(tmp_path, monkeypatch):
    (tmp_path / "KalimatiExtra.ttf").write_bytes(b"")
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    with pytest.raises(ReferenceFontError, match="unknown"):
        resolve_reference_font("kalimati-extra")
    with pytest.raises(ReferenceFontError, match="not found"):
        resolve_reference_font("kalimati-extra.ttf")


def test_reference_dirs_keeps_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    assert reference_dirs()[0] == Path(tmp_path)
    assert reference_dirs()[-1].name == "reference-fonts"


def test_resolves_all_alias_matches(tmp_path, monkeypatch):
    (tmp_path / "Sagarmatha.ttf").write_bytes(b"")
    (tmp_path / "Sagarmatha Bold.ttf").write_bytes(b"")
    monkeypatch.setenv("CIDMAP_REFERENCE_FONTS", str(tmp_path))
    assert [path.name for path in resolve_reference_fonts("sagarmatha")] == [
        "Sagarmatha.ttf", "Sagarmatha Bold.ttf"]
