"""
Read a structured JSON file from datasets/translations/ and upsert it to pgvector
as a National Assembly verbatim record.

Usage:
    python scripts/upsert_verbatim.py datasets/translations/Verbatim_2983.json
    python scripts/upsert_verbatim.py datasets/translations/Verbatim_*.json --dry-run

Pipeline:
    1. Load structured JSON
    2. Upsert verbatim record (na_id as dedup key; fall back to title)
    3. Chunk sections -> build context-prefixed text
    4. Generate embeddings via Gemini text-embedding-004
    5. Upsert all chunks into verbatim_chunks
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import requests

from config import EMBED_MODEL, GEMINI_API, load_env


class EmbeddingQuotaError(RuntimeError):
    pass


def get_embeddings(texts: list[str], api_key: str) -> list[list[float]]:
    results = []
    for i, text in enumerate(texts):
        resp = requests.post(
            f"{GEMINI_API}/{EMBED_MODEL}:embedContent",
            headers={"Content-Type": "application/json"},
            params={"key": api_key},
            json={
                "model": f"models/{EMBED_MODEL}",
                "content": {"parts": [{"text": text}]},
                "outputDimensionality": 768,
            },
        )
        if not resp.ok:
            err = resp.json().get("error", {}).get("message", resp.text[:300])
            if resp.status_code == 429 or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                raise EmbeddingQuotaError(f"Embedding API error: {err}")
            raise RuntimeError(f"Embedding API error: {err}")
        data = resp.json()
        embedding = data.get("embedding", {}).get("values", [])
        results.append(embedding)
        if i > 0 and i % 5 == 0:
            time.sleep(0.3)
    return results


def build_chunk_text(section: dict, session: dict, title: str) -> str:
    header = f"[Verbatim: {title} | Date: {session.get('date_bs','')} | Section: {section.get('name','')}]"
    parts = [header]
    summary = section.get("summary_en", "")
    if summary:
        parts.append(summary)
    speakers = section.get("speakers", [])
    if speakers:
        names = [s["name"] for s in speakers if s.get("name")]
        parts.append("Speakers: " + ", ".join(names))
    issues = section.get("key_issues", [])
    if issues:
        parts.append("Issues: " + "; ".join(issues))
    bills = section.get("bills_discussed", [])
    if bills:
        names = [b["name"] for b in bills if b.get("name")]
        parts.append("Bills: " + "; ".join(names))
    return "\n".join(parts)


def upsert_verbatim(structured: dict, api_key: str, db_url: str, dry_run: bool = False):
    session = structured.get("session", {})
    na_id = structured.get("na_id")
    title = structured.get("title") or Path(structured.get("_source_file", "unknown")).stem

    verbatim_data = {
        "na_id": na_id,
        "title": title,
        "title_np": structured.get("title_np"),
        "published_at": structured.get("published_at"),
        "date_bs": session.get("date_bs"),
        "date_ad": session.get("date_ad"),
        "meeting_type": session.get("meeting_type"),
        "meeting_number": session.get("meeting_number"),
        "chairperson": session.get("chairperson"),
        "adjournment_time": structured.get("adjournment_time"),
        "next_meeting_date": structured.get("next_meeting_date"),
        "source_pdf": structured.get("source_pdf"),
        "agenda_tags": structured.get("agenda_tags", []),
        "ministries_mentioned": structured.get("ministries_mentioned", []),
        "full_translation_en": structured.get("full_translation_en", ""),
    }

    if dry_run:
        print(f"[dry-run] would upsert verbatim: {title}", file=sys.stderr)
        return None

    sections = structured.get("sections", [])
    conn = psycopg.connect(db_url)
    cur = conn.cursor()

    cur.execute(
        """SELECT id, full_translation_en,
           (SELECT count(*) FROM verbatim_chunks c WHERE c.verbatim_id = v.id),
           (SELECT count(*) FROM verbatim_chunks c WHERE c.verbatim_id = v.id AND c.embedding IS NOT NULL)
           FROM verbatims v WHERE (na_id = %(na_id)s OR title = %(title)s)
           ORDER BY (na_id = %(na_id)s) DESC
           LIMIT 1""",
        {"na_id": na_id, "title": title},
    )
    existing = cur.fetchone()
    if (existing and existing[1] == verbatim_data["full_translation_en"]
            and existing[2] == existing[3] == len(sections)):
        print(f"[db] unchanged, skipping '{title}'", file=sys.stderr)
        cur.close()
        conn.close()
        return "skipped"

    # Dedup on na_id first, then title. A title collision with a different
    # na_id must update the existing row instead of raising a unique violation.
    existing_id = None
    matched_by_title = False
    if na_id:
        cur.execute("SELECT id FROM verbatims WHERE na_id = %s", (na_id,))
        row = cur.fetchone()
        if row:
            existing_id = row[0]
    if existing_id is None:
        cur.execute("SELECT id FROM verbatims WHERE title = %s", (title,))
        row = cur.fetchone()
        if row:
            existing_id = row[0]
            matched_by_title = True

    update_cols = """title=%(title)s, title_np=%(title_np)s,
       published_at=%(published_at)s::date,
       date_bs=%(date_bs)s, date_ad=%(date_ad)s::date,
       meeting_type=%(meeting_type)s, meeting_number=%(meeting_number)s,
       chairperson=%(chairperson)s, adjournment_time=%(adjournment_time)s,
       next_meeting_date=%(next_meeting_date)s, source_pdf=%(source_pdf)s,
       agenda_tags=%(agenda_tags)s, ministries_mentioned=%(ministries_mentioned)s,
       full_translation_en=%(full_translation_en)s, updated_at=NOW()"""

    if existing_id is not None:
        verbatim_data["id"] = existing_id
        if na_id and not matched_by_title:
            update_cols = "na_id=%(na_id)s, " + update_cols
        cur.execute(
            "UPDATE verbatims SET " + update_cols + " WHERE id=%(id)s",
            verbatim_data,
        )
        verbatim_id = existing_id
    else:
        cur.execute(
            """INSERT INTO verbatims (na_id, title, title_np, published_at,
               date_bs, date_ad, meeting_type, meeting_number, chairperson,
               adjournment_time, next_meeting_date, source_pdf,
               agenda_tags, ministries_mentioned, full_translation_en)
               VALUES (%(na_id)s, %(title)s, %(title_np)s, %(published_at)s::date,
               %(date_bs)s, %(date_ad)s::date, %(meeting_type)s,
               %(meeting_number)s, %(chairperson)s, %(adjournment_time)s, %(next_meeting_date)s,
               %(source_pdf)s, %(agenda_tags)s, %(ministries_mentioned)s, %(full_translation_en)s)
               RETURNING id""",
            verbatim_data,
        )
        verbatim_id = cur.fetchone()[0]

    chunk_texts = []
    chunk_rows = []

    for idx, section in enumerate(sections):
        chunk_text = build_chunk_text(section, session, title)
        chunk_texts.append(chunk_text)

        speakers = section.get("speakers", [])
        speaker_names = [s["name"] for s in speakers if s.get("name")]
        speaker_parties = list(set(s["party"] for s in speakers if s.get("party")))
        bills = section.get("bills_discussed", [])
        reports = section.get("reports_presented", [])

        chunk_rows.append((
            verbatim_id, idx, section.get("name"), chunk_text,
            section.get("summary_en"),
            speaker_names, speaker_parties if speaker_parties else None,
            section.get("key_issues", []),
            [b["name"] for b in bills if b.get("name")],
            reports,
        ))

    # Embed before deleting the old chunks so a quota failure cannot wipe them.
    try:
        print(f"[embed] {len(chunk_texts)} chunks...", file=sys.stderr)
        embeddings = get_embeddings(chunk_texts, api_key)
        print(f"[embed] done", file=sys.stderr)
    except EmbeddingQuotaError as e:
        print(f"[embed] quota exhausted: {e}", file=sys.stderr)
        conn.rollback()
        cur.close()
        conn.close()
        return "quota"
    except Exception as e:
        print(f"[embed] failed: {e}", file=sys.stderr)
        print(f"[embed] verbatim '{title}' left unchanged (retry later)", file=sys.stderr)
        conn.rollback()
        cur.close()
        conn.close()
        return "no_embeddings"

    cur.execute("DELETE FROM verbatim_chunks WHERE verbatim_id = %s", (verbatim_id,))
    for row, emb in zip(chunk_rows, embeddings):
        cur.execute(
            """INSERT INTO verbatim_chunks
               (verbatim_id, chunk_index, section_name, chunk_text, embedding,
                summary_en, speaker_names, speaker_parties, key_issues,
                bills_discussed, reports_presented)
               VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s)""",
            (row[0], row[1], row[2], row[3], emb, row[4], row[5], row[6], row[7], row[8], row[9]),
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f"[db] upserted verbatim '{title}' with {len(sections)} chunks", file=sys.stderr)
    return "ok"


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Upsert structured verbatim JSON to pgvector")
    parser.add_argument("files", nargs="+", help="Paths to structured JSON files")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--url", help="Database URL (default: DATABASE_URL env var)")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    db_url = args.url or os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    json_paths = []
    for pattern in args.files:
        for p in Path(".").glob(pattern):
            json_paths.append(p)

    if not json_paths:
        print("Error: no files matched", file=sys.stderr)
        sys.exit(1)

    for jp in json_paths:
        print(f"\n=== {jp.name} ===", file=sys.stderr)
        structured = json.loads(jp.read_text())
        structured["_source_file"] = jp.name
        outcome = upsert_verbatim(structured, api_key, db_url, dry_run=args.dry_run)
        if outcome == "quota":
            print("[embed] quota exhausted; stopping remaining files", file=sys.stderr)
            break


if __name__ == "__main__":
    main()