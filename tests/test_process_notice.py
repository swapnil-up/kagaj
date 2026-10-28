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
