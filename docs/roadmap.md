# Roadmap

## Current state (2026-11)

| Area | Status |
|---|---|
| Labour-migration panel | Active — `datasets/labour-migration/`, verified + fingerprinted |
| Parliamentary notices | Active — 174 of 182 translated; weekly scrape + daily backfill |
| Parliamentary verbatims | Active — 31 of 70 translated; 34 failed, resumable |
| Crime bulletins | Shipped — `datasets/crime/`, 58 bulletins, violent panels + charts |
| Budget redbook extraction | Active — `redbook_parser/` spatial-first; legacy engines frozen; **no shipped dataset yet** |
| KUKL water schedules | Active — `datasets/water/schedule.json`, 7 branches |
| `.gov.np` infrastructure | Experimental — `datasets/govweb/`, Phase 1 complete: 659/753 local levels attributed (87.52%); 20-host pilot sample |
| Dictionary | Shipped — StarDict output |
| CID mapping tool | Shipped — `cidmap/` |
| DDA drug prices | Experimental — scripts + plan, no shipped dataset |
| Dataset descriptors + index | Shipped — `datasets/<id>/dataset.json` + `datasets/index.json`; see `docs/dataset-manifest.md` |
| Dataset explorer | Shipped — `explorer/`, browser-side SQLite (sql.js); 19 tables, 2.4 MB gz |
| Vector search UI | None — pgvector tables exist; no query surface |
| Alerts | None |

## Positioning

Decided from a research pass comparing Kagaj against the existing Nepal open-data
landscape. Full reasoning is in the archived discussion; these are the load-bearing
points.

- **Kagaj is an extraction pipeline with an audit trail, not an aggregation layer.**
  Open Data Nepal (CKAN, ~630 datasets) re-hosts contributed files. Kagaj produces
  data from source PDFs with printed-total reconciliation, row-level `source_url`,
  and SHA-256-fingerprinted builds. That is the difference a researcher can cite.
- **Verifiability is the credibility story.** Because the pipelines are
  AI-assisted, the provenance layer (gold pages, audits, `build.json` hashes) is
  what earns trust — advertise the methodology, not the dataset count.
- **Spot-check the competition before claiming superiority.** The one completed
  check (labour migration) showed ODN's series stale by ~a decade against our
  FY2074/75–2082/83 panel. Parliament, water and budget are still unchecked.
- **The bottleneck is last-mile use, not extraction.** Prefer domains with an
  identified downstream user (researcher, journalist, civil-society org) over
  speculative extraction. Confirm demand before scaling a new domain.
- **Most of these domains are municipal/provincial, not federal.** Health,
  education, land and local budget sit at provincial/municipal level, so the shape
  of the problem is "hundreds of inconsistent sources", not "one ministry's PDFs".

## Track A — Foundation

Sequenced by value-per-effort. Nothing else in Track B should start until A1 is
solid.

1. **A1. Manifest/schema standardization.** One `dataset.json` per dataset under
   `datasets/<id>/`, a documented schema, a validator, and a generated
   `datasets/index.json` that any frontend can consume.
   *Done — contract in `docs/dataset-manifest.md`, CLI `python -m kagaj_core.manifest`.*
2. **A2. Dataset explorer (browser-side SQLite).** *Done — `explorer/` queries
   `output/explorer/kagaj.sqlite.gz` client-side via sql.js: browse, filter,
   sort, free SQL, CSV export. No backend, static-hostable. Build with
   `python datasets/build_sqlite.py`.*
3. **A3. Parliament search stays separate.** Semantic/vector search fits the
   document corpus (notices, verbatims, future gazette/court text). Linked from
   the explorer, not merged into it. pgvector needs a backend; a local embedding
   index is the alternative if staying static.
4. **A4. Freshness and diff views.** "Last updated" per dataset plus a diff of
   what changed between builds. The repo already fingerprints builds, so this is
   mostly surfacing what exists.
5. **A5. Cross-dataset joins as the actual product.** The compelling reason for
   one repo is joining datasets — budget lines against parliamentary debate,
   migration flows against district-level disaster or fiscal exposure — not a
   shared search box.
6. **A6. Catalog page.** A thin `kagaj` landing/catalog page under
   swapnilupadhyay.com.np, with the heavier explorer as its own static subsite.

## Track B — New data domains

Ranked by expected value. Every entry starts as a **scout** (cheap, time-boxed)
before it becomes a build.

| Domain | What it is | First step | Verdict |
|---|---|---|---|
| **Municipal budget** | Local-government budget/expenditure PDFs, hundreds of inconsistent sources | Scout 5–10 municipalities across provinces (include a remote district) to map real format variance | **Strongest next build.** `cidmap` applies directly — the same font problem publicly stalled Open Knowledge Nepal's "Data Spending Party" |
| **Auditor General** | `Mukhya Nihalak` annual audit reports of ministries/departments — findings against federal expenditure | Scout the Audit General's site for report formats, coverage years, and whether tables are machine-readable | **Scout.** Pairs naturally with the redbook: budget authorised vs. actually audited |
| **Import–export** | Customs/trade monthly and annual series (imports, exports, trade balance by HS code / partner country) | Scout Department of Customs + Trade & Commerce export data for structured files; check whether ODN already carries it and how fresh | **Scout.** Likely Excel/CSV rather than PDF — cheapest extraction shape of the three budget-adjacent domains |
| **Gazette + court documents** | Narrative, cross-referential corpora — the first documents besides parliament where semantic search genuinely fits | Survey existing Nepali legal-digitization efforts first (Law Commission, prior judgment scrapers) so we don't duplicate | **Survey first.** Decide redaction/anonymization policy *before* ingesting; court data carries real sensitivity |
| **Crime** | CID monthly bulletins | Continue as coverage allows; fill known gaps | **Shipped** — maintain |
| **Government web infrastructure** | Passive observation of `.gov.np` hosting, DNS, TLS and HTTP behaviour | Phase 2: replace the pilot sample with an attributed, multidomain universe; multi-vantage availability; RDAP provider attribution; certificate timeline; foreign-edge dependency | **Experimental** — Phase 1 complete (659/753 attributed, gate passed); paper framing is hosting concentration and availability, not a vulnerability audit |
| **BIPAD (disaster)** | Already-structured government portal | Ask NDRRMA / Youth Innovation Lab what technical gap remains | **Not a build.** Consume as an *input* to cross-dataset analysis, or partner — don't rebuild a working system |
| **HMIS / IEMIS (health, education)** | Collection works; public release doesn't | Approach as an access/relationships question, ideally alongside a partner org | **Partnership, not extraction.** Different skill from what Kagaj does |
| **Land records** | NeLIS runs on a private, access-controlled network | Revisit only via Survey Department or academic GIS partnership | **Deprioritize.** Open cadastral slice is a computer-vision research problem outside this toolchain |

## Track C — Nepali text pipeline (quota-aware)

Applies to parliament now and gazette/court if adopted.

1. **Structural chunking is free.** Split on notice numbers, section headings,
   numbered paragraphs, judgment boundaries using PyMuPDF spans — the same
   spatial-first approach as `redbook_parser`. Gemini is for translation and
   field extraction, never for locating chunk boundaries.
2. **Embed, don't translate, to index.** Local multilingual embeddings (e.g.
   multilingual-e5) let Nepali text be searched directly. Translation becomes a
   presentation-layer step.
3. **Translation is lazy and queued.** Translate only what a user opens, plus a
   quota-sized daily background batch. Track `translated: bool` per chunk the way
   `analysis_safe` is tracked; the UI shows "Nepali only" vs "translated" rather
   than blocking ingestion.

## Next

1. **Close the verbatim gap.** Re-run the checkpointed processor to reduce the
   34 failures, and record persistent failures with the reason.
2. **Archive.org backfill** for pre-2025 DoFE monthly/quarterly/yearly reports
   (Preeti decoder landed; ≥3 layout families remain).
3. **Budget dataset.** Publish a cleaned redbook extract under `datasets/` once
   the verification pass is complete.
4. **DDA drug prices.** Finish the experimental pipeline and decide whether the
   output is stable enough to ship.

## Non-goals

- Image pre-processing (deskew/contrast) — inputs are digital PDFs.
- Re-introducing the retired Vue/FastAPI uploader.
- WhatsApp Business API (Telegram first, if alerts are built).
- Building a competing disaster-data portal (BIPAD already exists and works).
- Independent extraction of individual land records (access-restricted by design).
- Translating the whole corpus before it can be searched (see Track C).

## Decisions log

| Date | Decision |
|---|---|
| 2026-07 | One Gemini call returns both `full_translation_en` and structured fields |
| 2026-07 | pgvector from the first DB write; no SQLite intermediate |
| 2026-10 | Repo repositioned as `kagaj` around datasets + extractors |
| 2026-10 | Web app (Vue/FastAPI/Docker/HF) removed |
| 2026-10 | Committed outputs consolidated under `datasets/` |
| 2026-11 | Positioning: extraction-with-audit-trail, not an aggregator like ODN |
| 2026-11 | Foundation (manifests → explorer) precedes any new domain |
| 2026-11 | Semantic search scoped to document corpora; tabular data gets filter/browse |
| 2026-11 | Municipal budget chosen as next build; BIPAD excluded as a build target |
| 2026-11 | Auditor General and import–export added as scout candidates |
| 2026-11 | `.gov.np` observation added as a fourth extraction family; grain is hostname, attribution is a separate join |

> Note: external claims above (ODN coverage, BIPAD status, NeLIS access model,
> Data Spending Party history) come from an AI-assisted research pass and should
> be re-verified before being cited publicly.
