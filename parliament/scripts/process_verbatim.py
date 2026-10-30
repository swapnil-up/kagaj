"""Process pending National Assembly verbatims: download → OCR → Gemini.

Verbatims are 30+ page meeting records (often >150KB OCR text), far too
large for a single Gemini translation call. Workaround: OCR text is split
into character-budgeted segments, each translated independently, then
re-merged into one structured JSON so downstream (upsert_verbatim.py)
sees the same schema as notices.

Big files (OCR text, full English translation) go to output/verbatims/
(gitignored). Only the structured JSON lands in datasets/translations/ so the repo
stays lean at ~50KB per verbatim.

Per-segment checkpointing: each completed segment is written to
output/verbatims/{stem}.segments/{idx}-{hash}.json as it finishes, so if
Gemini credits run out mid-document the next run resumes at the first
unfinished segment instead of re-translating from segment 1. The cache is
keyed on the segment text hash so any OCR drift invalidates only the
affected segments. The cache directory is deleted once the whole verbatim
is merged and saved. On GitHub Actions the output/verbatims dir is
persisted across runs via the actions/cache service (see
translate-verbatims.yml).

Failures are recorded in the manifest as status=failed with failure_kind,
last_error, failed_at, and attempts. Quota exhaustion stays pending with
failure_kind=quota; truncated/rate-limited responses fail with their own kinds.
Use --retry-failed to retry failures below --max-attempts (default 3). Metadata
is cleared when the verbatim succeeds.

Usage:
    .venv/bin/python scripts/process_verbatim.py --max-count 1
    .venv/bin/python scripts/process_verbatim.py --retry-failed -n 3
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib3
from datetime import datetime, timezone
from pathlib import Path

import requests

from kagaj_core import llm as core_llm

from config import (
    ADAPTIVE_BUDGET_RETRIES,
    GEMINI_MODEL,
    GEMINI_SYSTEM_INSTRUCTION,
    GEMINI_TEMPERATURE,
    HEADERS,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    RETRY_DELAY,
    SEGMENT_CHARS,
    TRANSLATIONS_DIR,
    VERBATIM_TIMEOUT,
    VERBATIMS_MANIFEST,
    VERBATIMS_OUTPUT_DIR,
    tls_verify,
    load_env,
)
from schema import VERBATIM_PROMPT, build_schema

if not tls_verify():
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MANIFEST = VERBATIMS_MANIFEST
DEFAULT_MAX_ATTEMPTS = 3
MAX_ERROR_CHARS = 1000
FAILURE_FIELDS = ("failure_kind", "last_error", "failed_at", "attempts")

VERBATIM_SCHEMA_DESC = build_schema(
    body="National Assembly",
    context="this segment as a single narrative string",
    date_suffix=" if mentioned",
    section_examples="Opening, Questions, Zero Hour, Main Business, Adjournment",
    speaker_label="speaker",
    search_label="verbatims",
)


def load_manifest() -> list:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return []


def save_manifest(verbatims: list):
    MANIFEST.write_text(
        json.dumps(verbatims, indent=2, ensure_ascii=False) + "\n")
    print(f"[manifest] saved {len(verbatims)} entries", file=sys.stderr)


def _attempts(verbatim: dict) -> int:
    try:
        return int(verbatim.get("attempts") or 0)
    except (TypeError, ValueError):
        return 0


def pick_pending(verbatims: list, *, retry_failed: bool = False,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 skip: set[int] | None = None) -> int | None:
    skip = skip or set()
    for i, v in enumerate(verbatims):
        if i in skip:
            continue
        status = v.get("status")
        if status == "pending":
            pass
        elif retry_failed and status == "failed" and _attempts(v) < max_attempts:
            pass
        else:
            continue
        url = v.get("attachment_url", "")
        if not url or not url.endswith(".pdf"):
            continue
        return i
    return None


def _record_failure(verbatim: dict, kind: str, message: str,
                    *, status: str = "failed") -> None:
    verbatim["status"] = status
    verbatim["failure_kind"] = kind
    verbatim["last_error"] = str(message)[:MAX_ERROR_CHARS]
    verbatim["failed_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    verbatim["attempts"] = _attempts(verbatim) + 1


def _record_success(verbatim: dict, result: dict) -> None:
    verbatim.update(result)
    verbatim["status"] = "done"
    for field in FAILURE_FIELDS:
        verbatim.pop(field, None)


def fetch_with_retry(url: str, **kwargs) -> tuple[requests.Response | None, str]:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=VERBATIM_TIMEOUT, verify=tls_verify(), **kwargs)
            resp.raise_for_status()
            return resp, ""
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"[retry] {url} ({e}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
    print(f"[error] {url}: {last_err}", file=sys.stderr)
    return None, str(last_err or "request failed")


def download_pdf(pdf_url: str, dest: Path) -> tuple[bool, str]:
    print(f"[download] {pdf_url}")
    try:
        resp, error = fetch_with_retry(pdf_url)
        if not resp:
            return False, f"download failed: {error}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        print(f"[download] saved {len(resp.content)} bytes to {dest}")
        return True, ""
    except Exception as e:
        print(f"[error] download: {e}", file=sys.stderr)
        return False, f"download failed: {e}"


def dedup_lines(text: str) -> str:
    lines = text.splitlines()
    result = [lines[0]] if lines else []
    for i in range(1, len(lines)):
        if lines[i] != lines[i - 1]:
            result.append(lines[i])
    return "\n".join(result)


def run_ocr(pdf_path: Path) -> str:
    """Extract Devanagari text. Reuses an existing {stem}-ocr.txt so
    segment inputs stay deterministic across runs (the resume anchor)."""
    stem = pdf_path.stem
    ocr_txt = VERBATIMS_OUTPUT_DIR / f"{stem}-ocr.txt"

    if ocr_txt.exists():
        text = ocr_txt.read_text(encoding="utf-8")
        print(f"[ocr] reused cached {ocr_txt} ({len(text):,} chars)", file=sys.stderr)
        return text

    bill_tracker = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable, str(bill_tracker / "pdf_to_text.py"),
        str(pdf_path),
        "-o", str(ocr_txt),
    ]
    print(f"[ocr] OCR only -> {ocr_txt}", file=sys.stderr)
    VERBATIMS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or "") + (result.stdout or "")
        raise RuntimeError(err[-500:])

    if ocr_txt.exists():
        ocr_txt.write_text(dedup_lines(ocr_txt.read_text()), encoding="utf-8")

    text = ocr_txt.read_text(encoding="utf-8")
    print(f"[ocr] extracted {len(text):,} chars", file=sys.stderr)
    return text


def segment_text(text: str, target_chars: int = SEGMENT_CHARS) -> list[str]:
    lines = text.splitlines(keepends=True)
    segments = []
    cur = []
    cur_len = 0
    for line in lines:
        cur.append(line)
        cur_len += len(line)
        if cur_len >= target_chars:
            segments.append("".join(cur))
            cur = []
            cur_len = 0
    if cur:
        segments.append("".join(cur))
    return segments


def compute_segment_hash(text: str) -> str:
    """Stable 10-char SHA-1 of segment content, used to key the checkpoint."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def get_segment_cache_path(stem: str, idx: int, text: str) -> Path:
    """Path to output/verbatims/{stem}.segments/{idx:03d}-{hash}.json."""
    cache_dir = VERBATIMS_OUTPUT_DIR / f"{stem}.segments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{idx:03d}-{compute_segment_hash(text)}.json"


def load_cached_segment(cache_path: Path) -> dict | None:
    """Return the cached segment result, or None if missing/corrupt.

    A corrupt or 0-byte file (abrupt runner death, bad cache restore) is
    deleted and treated as a cache miss so it gets re-translated.
    """
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("full_translation_en"):
            return data
        raise ValueError("incomplete segment result")
    except Exception as e:
        print(f"[cache] corrupt {cache_path.name} ({e}) — dropping", file=sys.stderr)
        try:
            cache_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def save_cached_segment(cache_path: Path, data: dict):
    """Atomically write a segment result to disk."""
    temp_path = cache_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(temp_path, cache_path)


def cleanup_segment_cache(stem: str):
    """Delete the segment checkpoint dir after a full successful merge."""
    cache_dir = VERBATIMS_OUTPUT_DIR / f"{stem}.segments"
    if not cache_dir.exists():
        return
    for f in cache_dir.iterdir():
        try:
            f.unlink()
        except OSError:
            pass
    try:
        cache_dir.rmdir()
        print(f"[cache] cleared {cache_dir}", file=sys.stderr)
    except OSError:
        pass


def call_gemini_segment(segment_text: str, idx: int, total: int, api_key: str) -> dict:
    prompt = VERBATIM_PROMPT.format(
        schema=VERBATIM_SCHEMA_DESC,
        idx=idx,
        total=total,
        segment_text=segment_text,
    )
    budget = core_llm.output_token_budget(segment_text, cap=MAX_OUTPUT_TOKENS)
    try:
        return core_llm.call_structured(
            prompt,
            api_key=api_key,
            model=GEMINI_MODEL,
            system_instruction=GEMINI_SYSTEM_INSTRUCTION,
            temperature=GEMINI_TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            max_retries=ADAPTIVE_BUDGET_RETRIES,
            retry_on_quota=False,
            budget=budget,
        )
    except core_llm.QuotaError as e:
        kind = "rpd" if e.kind == "rpd" else "rpm"
        raise RuntimeError(f"{kind.upper()}: {e}") from e
    except core_llm.TruncatedError as e:
        raise RuntimeError(f"TRUNCATED: {e}") from e
    except core_llm.GeminiError as e:
        raise RuntimeError(f"Gemini API error: {e}") from e


def merge_segments(results: list[dict]) -> dict:
    """Combine per-segment structured JSON into one document, mirroring the
    notice schema. Session metadata comes from the first mentioning it;
    lists are unioned; translation segments joined."""
    session = {}
    sections = []
    tag_counts = {}
    ministries = []
    all_speakers = []
    translations = []
    adjournment_time = None
    next_meeting_date = None

    def add_tag(t):
        if t not in tag_counts:
            tag_counts[t] = 0
        tag_counts[t] += 1

    for r in results:
        s = r.get("session") or {}
        for k, v in s.items():
            if v and not session.get(k):
                session[k] = v
        for sec in (r.get("sections") or []):
            sections.append(sec)
        for t in (r.get("agenda_tags") or []):
            add_tag(t)
        for m in (r.get("ministries_mentioned") or []):
            if m not in ministries:
                ministries.append(m)
        seen = {(x.get("name"), x.get("section")) for x in all_speakers}
        for sp in (r.get("all_speakers_mentioned") or []):
            if (sp.get("name"), sp.get("section")) not in seen:
                all_speakers.append(sp)
                seen.add((sp.get("name"), sp.get("section")))
        ft = (r.get("full_translation_en") or "").strip()
        if ft:
            translations.append(ft)
        adjournment_time = r.get("adjournment_time") or adjournment_time
        next_meeting_date = r.get("next_meeting_date") or next_meeting_date

    # Per-segment prompts each emit 5-15 tags; unioning across N segments
    # explodes the list (98 observed for a 10-segment verbatim). Keep the
    # most frequent tags — those recurring across segments describe the
    # whole document — capped at 15.
    MAX_AGENDA_TAGS = 15
    tags = [t for t, _ in sorted(tag_counts.items(), key=lambda kv: -kv[1])][:MAX_AGENDA_TAGS]

    return {
        "full_translation_en": "\n\n".join(translations),
        "session": session,
        "sections": sections,
        "agenda_tags": tags,
        "ministries_mentioned": ministries,
        "all_speakers_mentioned": all_speakers,
        "adjournment_time": adjournment_time,
        "next_meeting_date": next_meeting_date,
    }


def _phase_failure_kind(phase: str, message: str) -> str:
    if message.startswith("RPD"):
        return "quota"
    if message.startswith("RPM"):
        return "rate_limit"
    if message.startswith("TRUNCATED"):
        return "truncated"
    return phase


def process_one(verbatim: dict, index: int, verbatims: list) -> bool:
    v_id = verbatim.get("id")
    stem = f"Verbatim_{v_id}"
    pdf_url = verbatim.get("attachment_url")
    if not pdf_url:
        print("[error] no attachment URL", file=sys.stderr)
        _record_failure(verbatim, "no_pdf", "no attachment URL", status="no_pdf")
        save_manifest(verbatims)
        return False

    pdf_dest = VERBATIMS_OUTPUT_DIR / f"{stem}.pdf"

    downloaded, download_error = download_pdf(pdf_url, pdf_dest)
    if not downloaded:
        _record_failure(verbatim, "download",
                        download_error or "PDF download failed")
        save_manifest(verbatims)
        return False

    phase = "ocr"
    max_rpm_retries = 5
    for attempt in range(max_rpm_retries + 1):
        try:
            ocr_text = run_ocr(pdf_dest)
            phase = "translation"
            api_key = os.environ.get("GEMINI_API_KEY", "")

            if not api_key:
                print("[warn] GEMINI_API_KEY not set — OCR only, no translation", file=sys.stderr)
                result = {"ocr_path": str(VERBATIMS_OUTPUT_DIR / f"{stem}-ocr.txt")}
            else:
                segments = segment_text(ocr_text)
                print(f"[translate] {len(segments)} segments ({SEGMENT_CHARS} chars each)...", file=sys.stderr)
                results = []
                resumed = 0
                for seg_idx, seg in enumerate(segments, 1):
                    cache_path = get_segment_cache_path(stem, seg_idx, seg)
                    cached = load_cached_segment(cache_path)
                    if cached:
                        resumed += 1
                        print(f"  [seg] {seg_idx}/{len(segments)} (cached)", file=sys.stderr)
                        results.append(cached)
                        continue
                    print(f"  [seg] {seg_idx}/{len(segments)} ({len(seg):,} chars)...", file=sys.stderr)
                    res = call_gemini_segment(seg, seg_idx, len(segments), api_key)
                    save_cached_segment(cache_path, res)
                    results.append(res)
                if resumed:
                    print(f"[cache] resumed {resumed}/{len(segments)} segments", file=sys.stderr)

                structured = merge_segments(results)
                structured["_trigger"] = "verbatim"
                structured["na_id"] = verbatim.get("id")
                structured["title"] = verbatim.get("title", "")
                structured["title_np"] = verbatim.get("title_np", "")
                structured["published_at"] = verbatim.get("published_at")
                structured["source_pdf"] = pdf_url

                phase = "output"
                translation = structured.get("full_translation_en", "")
                trans_txt = VERBATIMS_OUTPUT_DIR / f"{stem}.txt"
                trans_txt.parent.mkdir(parents=True, exist_ok=True)
                trans_txt.write_text(translation, encoding="utf-8")
                print(f"[translate] full translation -> {trans_txt} ({len(translation):,} chars)", file=sys.stderr)

                out_json = TRANSLATIONS_DIR / f"{stem}.json"
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(structured, indent=2, ensure_ascii=False))
                print(f"[translate] structured JSON -> {out_json}", file=sys.stderr)

                result = {
                    "ocr_path": str(VERBATIMS_OUTPUT_DIR / f"{stem}-ocr.txt"),
                    "translated_path": str(trans_txt),
                    "structured_path": str(out_json),
                }

            _record_success(verbatim, result)
            save_manifest(verbatims)
            if api_key:
                cleanup_segment_cache(stem)
            print(f"[done] {verbatim.get('title', stem)}")
            return True

        except RuntimeError as e:
            msg = str(e)
            if msg.startswith(("RPM", "TRUNCATED")):
                if attempt < max_rpm_retries:
                    wait = min(2 ** (attempt + 2), 60)
                    print(f"[retry] {msg.split(':')[0].lower()}, retry {attempt + 1}/{max_rpm_retries} in {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                kind = _phase_failure_kind(phase, msg)
                print(f"[retry] max retries exceeded — marking '{verbatim.get('title', stem)}' as failed ({kind})", file=sys.stderr)
                _record_failure(verbatim, kind, msg)
                save_manifest(verbatims)
                return False
            if msg.startswith("RPD"):
                print(f"[quota] daily Gemini quota exhausted — keeping '{verbatim.get('title', stem)}' as pending", file=sys.stderr)
                _record_failure(verbatim, "quota", msg, status="pending")
                save_manifest(verbatims)
                return False
            kind = _phase_failure_kind(phase, msg)
            print(f"[error] processing ({kind}): {msg}", file=sys.stderr)
            _record_failure(verbatim, kind, msg)
            save_manifest(verbatims)
            return False
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            kind = _phase_failure_kind(phase, message)
            print(f"[error] processing ({kind}): unexpected {message}", file=sys.stderr)
            _record_failure(verbatim, kind, message)
            save_manifest(verbatims)
            return False
    return False


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Process pending verbatims through OCR + segmented Gemini translation")
    parser.add_argument("--max-count", "-n", type=int, default=0,
                        help="Max verbatims to process per run (0 = unlimited)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Also retry failed verbatims below --max-attempts")
    parser.add_argument("--max-attempts", type=int,
                        default=DEFAULT_MAX_ATTEMPTS,
                        help=f"Max recorded failures before a failed verbatim "
                             f"is not retried (default: {DEFAULT_MAX_ATTEMPTS})")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[warn] GEMINI_API_KEY not set — OCR only, no translation", file=sys.stderr)

    verbatims = load_manifest()
    if not verbatims:
        print("[error] verbatims.json empty — run scrape first", file=sys.stderr)
        return

    processed = 0
    attempted = set()
    max_count = args.max_count

    while True:
        if max_count and processed >= max_count:
            print(f"[limit] reached max-count ({max_count})", file=sys.stderr)
            break

        idx = pick_pending(verbatims, retry_failed=args.retry_failed,
                           max_attempts=args.max_attempts, skip=attempted)
        if idx is None:
            if args.retry_failed:
                print("[done] no pending or retryable failed verbatims")
            else:
                print("[done] no pending verbatims")
            break

        attempted.add(idx)
        ok = process_one(verbatims[idx], idx, verbatims)
        processed += 1

        if not ok and verbatims[idx].get("status") == "pending":
            print(f"[quota] stopping — {processed} verbatim(s) processed this run", file=sys.stderr)
            break


if __name__ == "__main__":
    main()