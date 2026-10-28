import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "parliament" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import process_notice as pn  # noqa: E402


def _notice(**overrides):
    entry = {
        "serial": "1.",
        "title": "Test notice",
        "url": "https://example.test/notices/1",
        "pdf_url": "https://example.test/a.pdf",
        "status": "pending",
    }
    entry.update(overrides)
    return entry


def test_pick_pending_accepts_pdf_and_image_attachments():
    notices = [_notice(pdf_url="https://example.test/a.pdf"), _notice(pdf_url="https://example.test/a.jpeg")]
    assert pn.pick_pending(notices) == 0
    assert pn.pick_pending(notices, skip={0}) == 1


def test_pick_pending_accepts_untitled_notice_with_url():
    notices = [_notice(title="(no title)", pdf_url=None)]
    assert pn.pick_pending(notices) == 0


def test_failed_notices_retry_only_when_requested_and_under_max_attempts():
    notices = [_notice(status="failed", attempts=1)]
    assert pn.pick_pending(notices) is None
    assert pn.pick_pending(notices, retry_failed=True, max_attempts=3) == 0
    assert pn.pick_pending(notices, retry_failed=True, max_attempts=1) is None


def test_pick_pending_skips_unsupported_and_unreachable_entries():
    notices = [
        _notice(pdf_url=None, url=None),
        _notice(pdf_url="https://example.test/a.zip"),
        _notice(pdf_url="https://example.test/a.pdf"),
    ]
    assert pn.pick_pending(notices) == 2


def test_notice_stem_unique_for_duplicate_titles():
    notices = [
        _notice(url="https://example.test/notices/11", title="Same"),
        _notice(url="https://example.test/notices/22", title="Same"),
    ]
    first = pn.notice_stem(notices[0], 0, notices)
    second = pn.notice_stem(notices[1], 1, notices)
    assert first != second
    assert first.endswith("_11")
    assert second.endswith("_22")


def test_notice_stem_stable_for_unique_title():
    notices = [_notice(title="Unique title")]
    assert pn.notice_stem(notices[0], 0, notices) == "Unique_title"


def test_notice_stem_untitled_uses_url_id():
    notices = [_notice(title="(no title)", url="https://example.test/notices/99")]
    assert pn.notice_stem(notices[0], 0, notices).endswith("_99")


def test_repair_collisions_requeues_done_entries(tmp_path, monkeypatch):
    manifest = tmp_path / "notices.json"
    monkeypatch.setattr(pn, "MANIFEST", manifest)
    notices = [
        _notice(url="https://example.test/notices/1", status="done",
                structured_path="datasets/translations/Same.json"),
        _notice(url="https://example.test/notices/2", status="done",
                structured_path="datasets/translations/Same.json"),
    ]
    assert pn._repair_collisions(notices)
    assert [n["status"] for n in notices] == ["pending", "pending"]
    assert "structured_path" not in notices[0]


def test_record_success_relativizes_paths_and_clears_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(pn, "REPO_ROOT", tmp_path)
    notice = _notice(status="failed", attempts=2, last_error="boom",
                     failure_kind="process", failed_at="now")
    out = tmp_path / "datasets" / "translations" / "Doc.json"
    out.parent.mkdir(parents=True)
    out.write_text("{}")
    pn._record_success(notice, {"structured_path": str(out)})
    assert notice["status"] == "done"
    assert notice["structured_path"] == "datasets/translations/Doc.json"
    for field in pn.FAILURE_FIELDS:
        assert field not in notice


def test_tls_verification_is_opt_in(monkeypatch):
    import config
    monkeypatch.delenv("PARLIAMENT_VERIFY_TLS", raising=False)
    assert config.tls_verify() is False
    monkeypatch.setenv("PARLIAMENT_VERIFY_TLS", "1")
    assert config.tls_verify() is True
