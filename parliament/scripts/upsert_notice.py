"""
Read a structured JSON file from datasets/translations/ and upsert it to pgvector.

Usage:
    python scripts/upsert_notice.py datasets/translations/Notice_2083-03-26.json
    python scripts/upsert_notice.py datasets/translations/Notice_2083-03-26.json --dry-run
    python scripts/upsert_notice.py datasets/translations/*.json                  # batch

Pipeline:
    1. Load structured JSON
    2. Upsert notice record (title as dedup key)
    3. Chunk sections -> build context-prefixed text
    4. Generate embeddings via Gemini text-embedding-004
    5. Upsert all chunks
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
    header = f"[Notice: {title} | Date: {session.get('date_bs','')} | Section: {section.get('name','')}]"
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


def upsert_notice(structured: dict, api_key: str, db_url: str, dry_run: bool = False):
    session = structured.get("session", {})
    title = Path(structured.get("_source_file", "unknown")).stem

    notice_data = {
        "title": title,
        "date_bs": session.get("date_bs"),
        "date_ad": session.get("date_ad"),
        "meeting_type": session.get("meeting_type"),
        "meeting_number": session.get("meeting_number"),
        "chairperson": session.get("chairperson"),
        "adjournment_time": structured.get("adjournment_time"),
        "next_meeting_date": structured.get("next_meeting_date"),
        "agenda_tags": structured.get("agenda_tags", []),
        "ministries_mentioned": structured.get("ministries_mentioned", []),
        "full_translation_en": structured.get("full_translation_en", ""),
    }

    if dry_run:
        print(f"[dry-run] would upsert notice: {title}", file=sys.stderr)
    else:
        sections = structured.get("sections", [])
        conn = psycopg.connect(db_url)
        cur = conn.cursor()

        cur.execute(
            """SELECT id, full_translation_en,
               (SELECT count(*) FROM chunks c WHERE c.notice_id = n.id),
               (SELECT count(*) FROM chunks c WHERE c.notice_id = n.id AND c.embedding IS NOT NULL)
               FROM notices n WHERE title = %s""",
            (title,),
        )
        existing = cur.fetchone()
        if (existing and existing[1] == notice_data["full_translation_en"]
                and existing[2] == existing[3] == len(sections)):
            print(f"[db] unchanged, skipping '{title}'", file=sys.stderr)
            cur.close()
            conn.close()
            return "skipped"

        cur.execute(
            """INSERT INTO notices (title, date_bs, date_ad, meeting_type, meeting_number,
               chairperson, adjournment_time, next_meeting_date,
               agenda_tags, ministries_mentioned, full_translation_en)
               VALUES (%(title)s, %(date_bs)s, %(date_ad)s::date, %(meeting_type)s,
               %(meeting_number)s, %(chairperson)s, %(adjournment_time)s, %(next_meeting_date)s,
               %(agenda_tags)s, %(ministries_mentioned)s, %(full_translation_en)s)
               ON CONFLICT (title) DO UPDATE SET
               date_bs=EXCLUDED.date_bs, date_ad=EXCLUDED.date_ad,
               meeting_type=EXCLUDED.meeting_type, meeting_number=EXCLUDED.meeting_number,
               chairperson=EXCLUDED.chairperson, adjournment_time=EXCLUDED.adjournment_time,
               next_meeting_date=EXCLUDED.next_meeting_date,
               agenda_tags=EXCLUDED.agenda_tags, ministries_mentioned=EXCLUDED.ministries_mentioned,
               full_translation_en=EXCLUDED.full_translation_en,
               updated_at=NOW()
               RETURNING id""",
            notice_data,
        )
        notice_id = cur.fetchone()[0]

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
                notice_id, idx, section.get("name"), chunk_text,
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
            conn.commit()
            cur.close()
            conn.close()
            return "quota"
        except Exception as e:
            print(f"[embed] failed: {e}", file=sys.stderr)
            print(f"[embed] notice '{title}' saved without embeddings (retry later)", file=sys.stderr)
            conn.commit()
            cur.close()
            conn.close()
            return "no_embeddings"

        cur.execute("DELETE FROM chunks WHERE notice_id = %s", (notice_id,))
        for row, emb in zip(chunk_rows, embeddings):
            cur.execute(
                """INSERT INTO chunks
                   (notice_id, chunk_index, section_name, chunk_text, embedding,
                    summary_en, speaker_names, speaker_parties, key_issues,
                    bills_discussed, reports_presented)
                   VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s)""",
                (row[0], row[1], row[2], row[3], emb, row[4], row[5], row[6], row[7], row[8], row[9]),
            )

        conn.commit()
        cur.close()
        conn.close()
        print(f"[db] upserted notice '{title}' with {len(sections)} chunks", file=sys.stderr)
        return "ok"


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Upsert structured notice JSON to pgvector")
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
        outcome = upsert_notice(structured, api_key, db_url, dry_run=args.dry_run)
        if outcome == "quota":
            print("[embed] quota exhausted; stopping remaining files", file=sys.stderr)
            break


if __name__ == "__main__":
    main()
