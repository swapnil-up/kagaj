"""
Read structured JSON files from datasets/translations/ and upsert DDA drug data to pgvector.

Usage:
    python scripts/upsert_dda.py datasets/translations/dda-gazette.json
    python scripts/upsert_dda.py datasets/translations/dda-*.json --dry-run
    python scripts/upsert_dda.py datasets/translations/dda-*.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from config import load_env


def upsert_medicines(structured: dict, db_url: str, dry_run: bool = False):
    source = structured.get("source", {})
    source_title = source.get("title", "unknown")
    source_type = source.get("document_type", "unknown")
    source_date_bs = source.get("date_bs")
    source_date_ad = source.get("date_ad")
    source_file = structured.get("_source_file", "")
    
    drugs = structured.get("drugs", [])
    if not drugs:
        print(f"[skip] no drugs in {source_title}", file=sys.stderr)
        return
    
    if dry_run:
        print(f"[dry-run] would upsert {len(drugs)} drugs from '{source_title}'", file=sys.stderr)
        return
    
    conn = psycopg.connect(db_url)
    cur = conn.cursor()
    
    upserted = 0
    for drug in drugs:
        drug_name_en = drug.get("drug_name_en")
        if not drug_name_en:
            continue
        
        drug_data = {
            "source_title": source_title,
            "source_date_bs": source_date_bs,
            "source_date_ad": source_date_ad,
            "source_type": source_type,
            "drug_name_en": drug_name_en,
            "drug_name_np": drug.get("drug_name_np"),
            "strength": drug.get("strength"),
            "dosage_form": drug.get("dosage_form"),
            "unit": drug.get("unit"),
            "mrp_npr": drug.get("mrp_npr"),
            "category": drug.get("category"),
            "manufacturer": drug.get("manufacturer"),
            "pack_size": drug.get("pack_size"),
            "schedule": drug.get("schedule"),
            "source_file": source_file,
        }
        
        cur.execute(
            """INSERT INTO dda_medicines
               (source_title, source_date_bs, source_date_ad, source_type,
                drug_name_en, drug_name_np, strength, dosage_form, unit, mrp_npr,
                category, manufacturer, pack_size, schedule, source_file)
               VALUES (%(source_title)s, %(source_date_bs)s, %(source_date_ad)s::date,
                       %(source_type)s, %(drug_name_en)s, %(drug_name_np)s, %(strength)s,
                       %(dosage_form)s, %(unit)s, %(mrp_npr)s, %(category)s,
                       %(manufacturer)s, %(pack_size)s, %(schedule)s, %(source_file)s)
               RETURNING id""",
            drug_data,
        )
        medicine_id = cur.fetchone()[0]
        
        # Upsert price record if we have MRP
        if drug.get("mrp_npr") is not None:
            cur.execute(
                """INSERT INTO dda_prices (medicine_id, price_npr, effective_date, source)
                   VALUES (%s, %s, %s::date, %s)
                   ON CONFLICT DO NOTHING""",
                (medicine_id, drug["mrp_npr"], source_date_ad, source_title),
            )
        
        upserted += 1
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"[db] upserted {upserted} medicines from '{source_title}'", file=sys.stderr)


def main():
    load_env()
    
    parser = argparse.ArgumentParser(description="Upsert DDA drug data to pgvector")
    parser.add_argument("files", nargs="+", help="Paths to structured JSON files")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--url", help="Database URL (default: DATABASE_URL env var)")
    args = parser.parse_args()
    
    db_url = args.url or os.environ.get("DATABASE_URL")
    if not db_url and not args.dry_run:
        print("Error: DATABASE_URL not set. Add to .env or pass --url", file=sys.stderr)
        sys.exit(1)
    
    json_paths = []
    for pattern in args.files:
        p = Path(pattern)
        if p.exists():
            json_paths.append(p)
        else:
            for match in Path(".").glob(pattern):
                json_paths.append(match)
    
    if not json_paths:
        print("Error: no files matched", file=sys.stderr)
        sys.exit(1)
    
    for jp in json_paths:
        print(f"\n=== {jp.name} ===", file=sys.stderr)
        structured = json.loads(jp.read_text())
        structured["_source_file"] = jp.name
        upsert_medicines(structured, db_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
