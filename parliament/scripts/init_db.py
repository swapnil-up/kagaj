"""
Create the pgvector schema for Kagaj.

Usage:
    python scripts/init_db.py                    # uses DATABASE_URL from .env
    python scripts/init_db.py --drop             # drops existing tables first
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from config import load_env


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS notices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT UNIQUE,
    date_bs TEXT,
    date_ad DATE,
    meeting_type TEXT,
    meeting_number TEXT,
    chairperson TEXT,
    adjournment_time TEXT,
    next_meeting_date TEXT,
    source_pdf TEXT,
    agenda_tags TEXT[],
    ministries_mentioned TEXT[],
    full_translation_en TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notice_id UUID NOT NULL REFERENCES notices(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section_name TEXT,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(768),  -- gemini-embedding-001 (outputDimensionality=768)
    summary_en TEXT,
    speaker_names TEXT[],
    speaker_parties TEXT[],
    key_issues TEXT[],
    bills_discussed TEXT[],
    reports_presented TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_chunks_notice_id ON chunks(notice_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS verbatims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    na_id INT UNIQUE,
    title TEXT UNIQUE,
    title_np TEXT,
    published_at DATE,
    date_bs TEXT,
    date_ad DATE,
    meeting_type TEXT,
    meeting_number TEXT,
    chairperson TEXT,
    adjournment_time TEXT,
    next_meeting_date TEXT,
    source_pdf TEXT,
    agenda_tags TEXT[],
    ministries_mentioned TEXT[],
    full_translation_en TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS verbatim_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    verbatim_id UUID NOT NULL REFERENCES verbatims(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    section_name TEXT,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(768),
    summary_en TEXT,
    speaker_names TEXT[],
    speaker_parties TEXT[],
    key_issues TEXT[],
    bills_discussed TEXT[],
    reports_presented TEXT[]
);

CREATE INDEX IF NOT EXISTS idx_verbatim_chunks_verbatim_id ON verbatim_chunks(verbatim_id);
CREATE INDEX IF NOT EXISTS idx_verbatim_chunks_embedding ON verbatim_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS dda_medicines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_title TEXT,
    source_date_bs TEXT,
    source_date_ad DATE,
    source_type TEXT,
    drug_name_en TEXT NOT NULL,
    drug_name_np TEXT,
    strength TEXT,
    dosage_form TEXT,
    unit TEXT,
    mrp_npr NUMERIC,
    category TEXT,
    manufacturer TEXT,
    pack_size TEXT,
    schedule TEXT,
    source_file TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dda_medicines_drug_name ON dda_medicines(drug_name_en);
CREATE INDEX IF NOT EXISTS idx_dda_medicines_strength ON dda_medicines(strength);

CREATE TABLE IF NOT EXISTS dda_prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medicine_id UUID NOT NULL REFERENCES dda_medicines(id) ON DELETE CASCADE,
    price_npr NUMERIC NOT NULL,
    effective_date DATE,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dda_prices_medicine_id ON dda_prices(medicine_id);
"""


DROP_SQL = """
DROP TABLE IF EXISTS dda_prices;
DROP TABLE IF EXISTS dda_medicines;
DROP TABLE IF EXISTS verbatim_chunks;
DROP TABLE IF EXISTS verbatims;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS notices;
"""


def main():
    load_env()

    parser = argparse.ArgumentParser(description="Initialize pgvector schema")
    parser.add_argument("--drop", action="store_true", help="Drop existing tables first")
    parser.add_argument("--url", help="Database URL (default: DATABASE_URL env var)")
    args = parser.parse_args()

    db_url = args.url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set. Add to .env or pass --url", file=sys.stderr)
        return

    print(f"[db] connecting to {db_url}", file=sys.stderr)
    conn = psycopg.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    if args.drop:
        print("[db] dropping existing tables...", file=sys.stderr)
        cur.execute(DROP_SQL)
        print("[db] done", file=sys.stderr)

    print("[db] creating schema...", file=sys.stderr)
    cur.execute(SCHEMA_SQL)
    print("[db] schema ready", file=sys.stderr)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
