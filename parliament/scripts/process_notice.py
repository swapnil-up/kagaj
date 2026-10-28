import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib3
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import (
    ADAPTIVE_BUDGET_RETRIES,
    GEMINI_API,
    GEMINI_MODEL,
    GEMINI_SYSTEM_INSTRUCTION,
    GEMINI_TEMPERATURE,
    HEADERS,
    HR_BASE,
    MAX_OUTPUT_TOKENS,
    MAX_RETRIES,
    NOTICES_MANIFEST,
    OUTPUT_DIR,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    TRANSLATIONS_DIR,
    load_env,
)
from schema import NOTICE_PROMPT, build_schema

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MANIFEST = NOTICES_MANIFEST
BASE = HR_BASE

STRUCTURED_SCHEMA_DESC = build_schema()
STRUCTURED_PROMPT = NOTICE_PROMPT


def load_manifest() -> list:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return []


def save_manifest(notices: list):
    MANIFEST.write_text(json.dumps(notices, indent=2, ensure_ascii=False))
    print(f"[manifest] saved {len(notices)} entries", file=sys.stderr)


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _attempts(notice: dict) -> int:
    try:
        return int(notice.get("attempts") or 0)
    except (TypeError, ValueError):
        return 0


def _supported_attachment(url: str) -> bool:
    return url.lower().split("?")[0].endswith((".pdf",) + IMAGE_EXTS)


def _record_failure(notice: dict, kind: str, message: str,
                    *, status: str = "failed") -> None:
    notice["status"] = status
    notice["failure_kind"] = kind
    notice["last_error"] = str(message)[:500]
    notice["failed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notice["attempts"] = _attempts(notice) + 1


def pick_pending(notices: list, *, retry_failed: bool = False,
                 max_attempts: int = 3, skip: set[int] | None = None) -> int | None:
    skip = skip or set()
    for i, n in enumerate(notices):
        if i in skip:
            continue
        status = n.get("status")
        if status == "pending":
            pass
        elif retry_failed and status == "failed" and _attempts(n) < max_attempts:
            pass
        else:
            continue
        pdf = n.get("pdf_url", "")
        if pdf and not _supported_attachment(pdf):
            continue
        if not pdf and not n.get("url"):
            continue
        return i
    return None


def fetch_with_retry(url: str, **kwargs) -> requests.Response | None:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"[retry] {url} ({e}), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
    print(f"[error] {url}: {last_err}", file=sys.stderr)
    return None


def fetch_page(url: str) -> BeautifulSoup | None:
    resp = fetch_with_retry(url)
    if resp:
        return BeautifulSoup(resp.text, "lxml")
    return None


def backfill_pdf_url(notice: dict) -> str | None:
    url = notice.get("url")
    if not url:
        return None
    soup = fetch_page(url)
    if not soup:
        return None
    for a in soup.select("a[href]"):
        href = a["href"]
        if "/uploads/attachments/" in href:
            if not href.startswith("http"):
                href = BASE + href
            return href
    for a in soup.select("a[href$='.pdf']"):
        href = a["href"]
        if not href.startswith("http"):
            href = BASE + href
        return href
    return None


def backfill_title(notice: dict) -> str | None:
    url = notice.get("url")
    if not url:
        return None
    soup = fetch_page(url)
    if not soup:
        return None
    for selector in ("h1", "h2", ".page-title", ".card-title"):
        el = soup.select_one(selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text and text != "(no title)":
                return text
    if soup.title:
        text = re.split(r"\s+[|\u2013-]\s+", soup.title.get_text(" ", strip=True))[0].strip()
        if text and text.lower() not in ("parliament", "hr.parliament.gov.np"):
            return text
    return None


def _image_to_pdf(src: Path, dest: Path) -> bool:
    try:
        from PIL import Image
        with Image.open(src) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(dest, "PDF", resolution=150)
        return True
    except Exception as e:
        print(f"[error] image conversion: {e}", file=sys.stderr)
        return False


def download_pdf(pdf_url: str, dest: Path) -> bool:
    print(f"[download] {pdf_url}")
    try:
        resp = fetch_with_retry(pdf_url)
        if not resp:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        print(f"[download] saved {len(resp.content)} bytes to {dest}")
        return True
    except Exception as e:
        print(f"[error] download: {e}", file=sys.stderr)
        return False


def dedup_lines(text: str) -> str:
    lines = text.splitlines()
    result = [lines[0]] if lines else []
    for i in range(1, len(lines)):
        if lines[i] != lines[i - 1]:
            result.append(lines[i])
    return "\n".join(result)


def _classify_gemini_error(err: str) -> str:
    lowered = err.lower()
    if any(p in lowered for p in ["rate limit", "high demand", "try again later"]):
        return "rpm"
    if any(p in err for p in ["429", "403", "RESOURCE_EXHAUSTED", "quota"]):
        return "rpd"
    return "other"


def _output_token_budget(ocr_text: str) -> int:
    chars = len(ocr_text)
    return max(8192, min(chars // 2, MAX_OUTPUT_TOKENS))


def run_ocr(pdf_path: Path) -> dict:
    stem = pdf_path.stem
    ocr_txt = TRANSLATIONS_DIR / f"{stem}-ocr.txt"
    api_key = os.environ.get("GEMINI_API_KEY", "")

    bill_tracker = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable, str(bill_tracker / "pdf_to_text.py"),
        str(pdf_path),
        "-o", str(ocr_txt),
    ]
    print(f"[ocr] OCR only -> {ocr_txt}")

    TRANSLATIONS_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or "") + (result.stdout or "")
        raise RuntimeError(err[-500:])

    if ocr_txt.exists():
        ocr_txt.write_text(dedup_lines(ocr_txt.read_text()), encoding="utf-8")

    result_dict = {"ocr_path": str(ocr_txt)}

    if api_key:
        print(f"[translate] structured Gemini extraction...", file=sys.stderr)
        ocr_text = ocr_txt.read_text(encoding="utf-8")
        structured = call_gemini_structured(ocr_text, api_key)

        translation = structured.get("full_translation_en", "")
        out_txt = TRANSLATIONS_DIR / f"{stem}.txt"
        out_txt.write_text(translation, encoding="utf-8")
        print(f"[translate] full translation -> {out_txt} ({len(translation)} chars)", file=sys.stderr)
        result_dict["translated_path"] = str(out_txt)

        out_json = TRANSLATIONS_DIR / f"{stem}.json"
        out_json.write_text(json.dumps(structured, indent=2, ensure_ascii=False))
        print(f"[translate] structured JSON -> {out_json}", file=sys.stderr)
        result_dict["structured_path"] = str(out_json)

    return result_dict


def call_gemini_structured(ocr_text: str, api_key: str) -> dict:
    prompt = STRUCTURED_PROMPT.format(schema=STRUCTURED_SCHEMA_DESC, ocr_text=ocr_text)
    budget = _output_token_budget(ocr_text)

    for attempt in range(ADAPTIVE_BUDGET_RETRIES):
        resp = requests.post(
            f"{GEMINI_API}/{GEMINI_MODEL}:generateContent",
            headers={"Content-Type": "application/json"},
            params={"key": api_key},
            json={
                "system_instruction": {
                    "parts": [{"text": GEMINI_SYSTEM_INSTRUCTION}]
                },
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": GEMINI_TEMPERATURE,
                    "maxOutputTokens": budget,
                },
            },
        )

        try:
            body = resp.json()
        except ValueError:
            body = {}

        if not resp.ok:
            err = body.get("error", {}).get("message", resp.text[:500])
            kind = _classify_gemini_error(err)
            if kind in ("rpm", "rpd"):
                raise RuntimeError(f"{kind.upper()}: {err}")
            raise RuntimeError(f"Gemini API error: {err}")

        candidates = body.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "")
        parts = candidate.get("content", {}).get("parts", [])
        if not parts:
            raise RuntimeError("Gemini returned empty content")

        text = parts[0].get("text", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            if finish_reason == "MAX_TOKENS":
                used = (body.get("usageMetadata") or {}).get("candidatesTokenCount") or budget
                grown = min(int(used * 1.5) + 2048, MAX_OUTPUT_TOKENS)
                if grown > budget:
                    print(f"[retry] truncated at {used} tokens, growing budget {budget} -> {grown}...", file=sys.stderr)
                    budget = grown
                    continue
            raise RuntimeError(f"TRUNCATED: Gemini response cut off mid-JSON ({e})")
        raise RuntimeError(f"Gemini returned invalid JSON ({e})")

    raise RuntimeError("TRUNCATED: Gemini response cut off mid-JSON after budget growth")


def process_one(notice: dict, index: int, notices: list) -> bool:
    title = notice.get("title") or ""
    if title in ("", "(no title)"):
        recovered = backfill_title(notice)
        if recovered:
            notices[index]["title"] = recovered
            notice = notices[index]
            save_manifest(notices)
            title = recovered
    title_slug = (title or f"notice_{index}").replace(" ", "_").replace("/", "_")[:80]

    pdf_url = notice.get("pdf_url")
    if not pdf_url:
        print(f"[backfill] fetching PDF URL...", file=sys.stderr)
        pdf_url = backfill_pdf_url(notice)
        if pdf_url:
            notices[index]["pdf_url"] = pdf_url
            save_manifest(notices)
        else:
            print(f"[error] no PDF found", file=sys.stderr)
            notices[index]["status"] = "no_pdf"
            save_manifest(notices)
            return False

    suffix = Path(pdf_url.split("?")[0]).suffix.lower()
    if suffix not in (".pdf",) + IMAGE_EXTS:
        suffix = ".pdf"
    download_dest = OUTPUT_DIR / f"{title_slug}{suffix}"
    pdf_dest = OUTPUT_DIR / f"{title_slug}.pdf"

    if not download_pdf(pdf_url, download_dest):
        _record_failure(notices[index], "download", "download failed")
        save_manifest(notices)
        return False

    if suffix in IMAGE_EXTS:
        if not _image_to_pdf(download_dest, pdf_dest):
            _record_failure(notices[index], "convert", "image to PDF conversion failed")
            save_manifest(notices)
            return False

    max_rpm_retries = 5
    for attempt in range(max_rpm_retries + 1):
        try:
            result = run_ocr(pdf_dest)
            notices[index].update(result)
            notices[index]["status"] = "done"
            save_manifest(notices)
            print(f"[done] {notice['title']}")
            return True
        except RuntimeError as e:
            msg = str(e)
            if msg.startswith(("RPM", "TRUNCATED")):
                if attempt < max_rpm_retries:
                    wait = min(2 ** (attempt + 2), 60)
                    print(f"[retry] {msg.split(':')[0].lower()}, retry {attempt + 1}/{max_rpm_retries} in {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"[retry] max retries exceeded — marking '{notice['title']}' as skipped", file=sys.stderr)
                _record_failure(notices[index], "rpm", msg, status="skipped")
                save_manifest(notices)
                return False
            if msg.startswith("RPD"):
                print(f"[quota] daily Gemini quota exhausted — keeping '{notice['title']}' as pending", file=sys.stderr)
                notices[index]["status"] = "pending"
                notices[index]["last_error"] = msg[:500]
                save_manifest(notices)
                return False
            print(f"[error] processing: {msg}", file=sys.stderr)
            _record_failure(notices[index], "process", msg)
            save_manifest(notices)
            return False
        except Exception as e:
            print(f"[error] processing: unexpected {type(e).__name__}: {e}", file=sys.stderr)
            _record_failure(notices[index], "unexpected", f"{type(e).__name__}: {e}")
            save_manifest(notices)
            return False


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Process pending notices through OCR + Gemini translation")
    parser.add_argument("--max-count", "-n", type=int, default=0,
                        help="Max notices to process per run (0 = unlimited)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Also retry failed notices below --max-attempts")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Max recorded failures before a failed notice is not retried")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[warn] GEMINI_API_KEY not set — OCR only, no translation", file=sys.stderr)

    notices = load_manifest()
    if not notices:
        print("[error] notices.json empty — run scrape first", file=sys.stderr)
        return

    processed = 0
    attempted = set()
    max_count = args.max_count

    while True:
        if max_count and processed >= max_count:
            print(f"[limit] reached max-count ({max_count})", file=sys.stderr)
            break

        idx = pick_pending(notices, retry_failed=args.retry_failed,
                           max_attempts=args.max_attempts, skip=attempted)
        if idx is None:
            if args.retry_failed:
                print("[done] no pending or retryable failed notices")
            else:
                print("[done] no pending notices")
            break

        attempted.add(idx)
        ok = process_one(notices[idx], idx, notices)
        processed += 1

        if not ok and (notices[idx].get("status") == "pending"
                       or notices[idx].get("failure_kind") == "quota"):
            print(f"[quota] stopping — {processed} notice(s) processed this run", file=sys.stderr)
            break


if __name__ == "__main__":
    main()