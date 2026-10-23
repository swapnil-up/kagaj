import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "parliament" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import process_verbatim as pv  # noqa: E402


def _verbatim(**overrides):
    entry = {
        "id": 9001,
        "title": "Test verbatim",
        "attachment_url": "https://example.test/test.pdf",
        "status": "pending",
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def no_manifest(monkeypatch):
    monkeypatch.setattr(pv, "save_manifest", lambda entries: None)


def test_pending_to_failed_to_retry_to_done(monkeypatch, no_manifest):
    verbatim = _verbatim()
    entries = [verbatim]
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(pv, "download_pdf", lambda url, dest: (True, ""))

    def broken_ocr(path):
        raise RuntimeError("pdftotext failed")

    monkeypatch.setattr(pv, "run_ocr", broken_ocr)

    assert pv.process_one(verbatim, 0, entries) is False
    assert verbatim["status"] == "failed"
    assert verbatim["failure_kind"] == "ocr"
    assert verbatim["last_error"] == "pdftotext failed"
    assert verbatim["attempts"] == 1
    assert verbatim["failed_at"]
    assert pv.pick_pending(entries) is None
    assert pv.pick_pending(entries, retry_failed=True) == 0

    monkeypatch.setattr(pv, "run_ocr", lambda path: "speech text")

    assert pv.process_one(verbatim, 0, entries) is True
    assert verbatim["status"] == "done"
    assert verbatim["ocr_path"]
    for field in pv.FAILURE_FIELDS:
        assert field not in verbatim
    assert pv.pick_pending(entries, retry_failed=True) is None


def test_failed_retry_stops_at_max_attempts():
    entry = _verbatim(status="failed", attempts=3)
    assert pv.pick_pending([entry], retry_failed=True, max_attempts=3) is None

    entry["attempts"] = 2
    assert pv.pick_pending([entry], retry_failed=True, max_attempts=3) == 0

    pending = _verbatim(attempts=99)
    assert pv.pick_pending([pending], retry_failed=True, max_attempts=3) == 0


def test_pick_pending_does_not_repeat_an_attempt_in_the_same_run():
    first = _verbatim(id=1, status="failed", attempts=0)
    second = _verbatim(id=2, status="failed", attempts=0)

    assert pv.pick_pending([first, second], retry_failed=True) == 0
    assert pv.pick_pending([first, second], retry_failed=True,
                           skip={0}) == 1


def test_quota_failure_stays_pending_and_is_not_truncation(
        monkeypatch, no_manifest, tmp_path):
    verbatim = _verbatim(id=9002)
    entries = [verbatim]
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(pv, "download_pdf", lambda url, dest: (True, ""))
    monkeypatch.setattr(pv, "run_ocr", lambda path: "speech text")
    monkeypatch.setattr(pv, "segment_text", lambda text: ["segment"])
    monkeypatch.setattr(pv, "get_segment_cache_path",
                        lambda stem, idx, text: tmp_path / f"{idx}.json")
    monkeypatch.setattr(pv, "load_cached_segment", lambda path: None)

    def quota_error(*args):
        raise RuntimeError("RPD: daily quota exhausted")

    monkeypatch.setattr(pv, "call_gemini_segment", quota_error)

    assert pv.process_one(verbatim, 0, entries) is False
    assert verbatim["status"] == "pending"
    assert verbatim["failure_kind"] == "quota"
    assert verbatim["attempts"] == 1


def test_truncation_failure_is_distinct_from_ocr(
        monkeypatch, no_manifest, tmp_path):
    verbatim = _verbatim(id=9003)
    entries = [verbatim]
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(pv.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pv, "download_pdf", lambda url, dest: (True, ""))
    monkeypatch.setattr(pv, "run_ocr", lambda path: "speech text")
    monkeypatch.setattr(pv, "segment_text", lambda text: ["segment"])
    monkeypatch.setattr(pv, "get_segment_cache_path",
                        lambda stem, idx, text: tmp_path / f"{idx}.json")
    monkeypatch.setattr(pv, "load_cached_segment", lambda path: None)

    def truncated(*args):
        raise RuntimeError("TRUNCATED: response cut off")

    monkeypatch.setattr(pv, "call_gemini_segment", truncated)

    assert pv.process_one(verbatim, 0, entries) is False
    assert verbatim["status"] == "failed"
    assert verbatim["failure_kind"] == "truncated"
    assert verbatim["attempts"] == 1
