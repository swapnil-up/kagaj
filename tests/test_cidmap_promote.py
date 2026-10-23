import json
from types import SimpleNamespace

from cidmap import cli, confidence, registry
from cidmap.confidence import PromotionCandidate


def _candidate(value="ि", blockers=()):
    return PromotionCandidate(
        font_id="KLMNGO+Kalimati",
        cid=7,
        value=value,
        score=0.85,
        status="confirmed",
        support=2,
        reasons=("registry confirmed by 2 documents",),
        blockers=tuple(blockers),
    )


def _args(tmp_path, *, apply=False, json_path=None):
    return SimpleNamespace(
        pdf="fake.pdf",
        store=str(tmp_path / "store.json"),
        registry=str(tmp_path / "registry.json"),
        reference_font=None,
        lexicon=None,
        max_pages=None,
        cids=None,
        apply=apply,
        json=json_path,
    )


def test_dry_run_does_not_write_store(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(registry, "load", lambda path: registry.empty_registry())
    monkeypatch.setattr(confidence, "promote_document",
                        lambda *args, **kwargs: [_candidate()])
    assert cli.cmd_promote(_args(tmp_path)) == 0
    assert not (tmp_path / "store.json").exists()


def test_apply_writes_promotable_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(registry, "load", lambda path: registry.empty_registry())
    monkeypatch.setattr(confidence, "promote_document",
                        lambda *args, **kwargs: [_candidate()])
    assert cli.cmd_promote(_args(tmp_path, apply=True)) == 0
    saved = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert saved["fonts"]["KLMNGO+Kalimati"]["7"] == "ि"
    assert saved["cids"]["7"]["_meta"]["source"] == "promote"


def test_blocked_candidate_is_not_applied(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(registry, "load", lambda path: registry.empty_registry())
    monkeypatch.setattr(
        confidence, "promote_document",
        lambda *args, **kwargs: [_candidate(blockers=("registry conflict",))])
    assert cli.cmd_promote(_args(tmp_path, apply=True)) == 0
    assert not (tmp_path / "store.json").exists()


def test_json_report_contains_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_doc", lambda args: object())
    monkeypatch.setattr(registry, "load", lambda path: registry.empty_registry())
    monkeypatch.setattr(confidence, "promote_document",
                        lambda *args, **kwargs: [_candidate()])
    out = tmp_path / "report.json"
    assert cli.cmd_promote(
        _args(tmp_path, apply=True, json_path=str(out))) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["candidates"][0]["promotable"] is True
    assert payload["promoted"][0]["cid"] == 7
