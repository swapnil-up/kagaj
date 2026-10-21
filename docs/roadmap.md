# Roadmap

## Current state (2026-10)

| Area | Status |
|---|---|
| Labour-migration panel | Active — `datasets/labour-migration/`, verified + fingerprinted |
| Parliamentary notices | Active — 174 of 182 translated; weekly scrape + daily backfill |
| Parliamentary verbatims | Active — 31 of 70 translated; 34 failed, resumable |
| Budget redbook extraction | Active — `redbook_parser/` spatial-first; legacy engines frozen |
| KUKL water schedules | Active — `datasets/water/schedule.json`, 7 branches |
| Dictionary | Shipped — StarDict output |
| CID mapping tool | Shipped — `cidmap/` |
| DDA drug prices | Experimental — scripts + plan, no shipped dataset |
| Vector search UI | None — pgvector tables exist; no query surface |
| Alerts | None |

## Next

1. **Close the verbatim gap.** Re-run the checkpointed processor to reduce the
   34 failures, and record persistent failures with the reason.
2. **Archive.org backfill** for pre-2025 DoFE monthly/quarterly/yearly reports
   (Preeti decoder landed; ≥3 layout families remain).
3. **Budget dataset.** Publish a cleaned redbook extract under `datasets/` once
   the verification pass is complete.
4. **DDA drug prices.** Finish the experimental pipeline and decide whether the
   output is stable enough to ship.
5. **Search surface (optional).** Build a small read-only query app on top of
   the existing pgvector tables — as a separate project, not in this repo.

## Non-goals

- Image pre-processing (deskew/contrast) — inputs are digital PDFs.
- Re-introducing the retired Vue/FastAPI uploader.
- WhatsApp Business API (Telegram first, if alerts are built).

## Decisions log

| Date | Decision |
|---|---|
| 2026-07 | One Gemini call returns both `full_translation_en` and structured fields |
| 2026-07 | pgvector from the first DB write; no SQLite intermediate |
| 2026-10 | Repo repositioned as `kagaj` around datasets + extractors |
| 2026-10 | Web app (Vue/FastAPI/Docker/HF) removed |
| 2026-10 | Committed outputs consolidated under `datasets/` |
