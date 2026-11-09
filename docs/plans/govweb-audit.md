# govweb — passive observation of Nepal's `.gov.np` web infrastructure

Status: **Phase 0 complete. Phase 1 complete** (attribution 94.56% of the 753
local levels, gate passed). **Phase 3 started** (entity classification of the
whole apex universe). Phase 2 (measurement and analysis) is next.

This plan supersedes the `dinfra` roadmap that preceded it. `dinfra` was a
standalone harness project; `govweb` is its Kagaj port, with the scope corrected
from "753 municipal websites" to "the whole observed `.gov.np` universe, with
local-level attribution as one lens over it".

## Why the scope changed

The `dinfra` pilot measured 20 hostnames selected lexicographically from the full
`.gov.np` Certificate Transparency inventory. Those hostnames are central
ministries, courts, and government banks — not local governments. Exact
municipality+district matching resolved **0 of 765** roster entries, the HTTP
collector obtained usable headers for **6 of 20** hosts, and **12 of 20**
disallowed the crawler in `robots.txt`. TLS was never collected. As a study of
municipal e-governance the pilot cannot carry a claim.

The raw material is better than the pilot suggested. A read-only scout over the
175 municipality websites recorded in Wikidata found:

- 163 hostnames resolve;
- **130 of 163 (80%) resolve into a single government /22,
  `103.69.124.0/22` (DOITGON-NP, Department of Information Technology)**;
- **101 hostnames resolve to one address, `103.69.127.8`**, which accepted no
  TCP connection on port 80 or 443 from this host or from an independent
  external vantage, while hosts on neighbouring addresses answered in
  40–140 ms.

That is a concentration-and-resilience story, not a vulnerability story. It is
also measurable passively and at scale, which is what the original idea wanted.

## Decisions

| Decision | Choice |
|---|---|
| Paper framing | hosting concentration, availability, foreign edge dependency — not a security/vulnerability audit |
| Universe | all observed `.gov.np` hostnames; the 753 local levels are a lens, not the grain |
| Storage grain | hostname-first; attribution is a separate evidence-bearing join |
| Raw observations | committed as `role: raw` artifacts, because a live probe cannot be reproduced byte-for-byte |
| Responsible disclosure | deferred until the build is complete; log it, do not publish site-level findings first |
| Port order | port `dinfra` as-is, then expand; do not rewrite the collectors before they are in the repo |

## Phase 0 — port as-is (complete)

Delivered:

- `govweb/` package: roster, CT discovery, MoFAGA discovery, TLS, HTTP headers,
  hosting, DNS/mail, robots and script collectors, analyzer, builder and
  verifier, behind `python -m govweb.cli`.
- `datasets/govweb/` with the roster, CT inventory and source response, the five
  committed observation sets, nine tidy CSVs, `build.json`, `audit_report.json`,
  `audit_summary.md`, `reconciliation.json`, `dataset.json`, `DATASET.md` and
  `codebook.json`.
- 165 ported offline tests under `tests/test_govweb_*.py`.
- `pyproject.toml` packaging and the fourth extraction family in
  `docs/architecture.md`: **network observation**.

Paths resolve relative to the package. Regenerable state (per-host caches) lives
under `output/govweb/`; committed data lives under `datasets/govweb/`.

## Phase 1 — universe and attribution (complete)

Goal: make the local-level lens usable without inventing links.

1. **Roster reconciliation.** Done. 765 → 753: 12 extra records are adjudicated in
   `roster_adjudication.json` (9 `superseded`, 2 `duplicate`, 1 `misplaced`),
   each with the superseding roster id and evidence. No row was deleted to reach
   the target.
2. **Universe tiers.** U1 = all discovered hostnames (2,782 after merging
   attribution sources into the CT inventory); U2 = apex hostnames; U3 = the 659
   attributed local levels.
3. **Attribution triangulation.** Done. The MoFAGA directory was unreachable, so
   the local-body e-office directory (`dcc-localbody-list`, 753 rows) became the
   primary source. Authority order: `manual` > `localbody_directory` >
   `wikidata_p856` > `ct_hostname_slug` > `osm_website`. Every link keeps
   `method`, `confidence`, `evidence_url`, `evidence_note` and `decided_at`.
   Result: 659/753 local levels (87.52%), 706 accepted hostname links —
   607 directory, 86 Wikidata, 13 CT slug.
4. **Coverage validation.** Not run. Remaining work for Phase 2 prep: sample the
   94 unresolved local levels to estimate how many actually have no discoverable
   site.
5. **Gate before Phase 2. Passed.** Attribution is 87.52% ≥ 40%, and
   `103.69.127.8` still refused TCP 80 and 443 on 2026-11-09, more than 48 hours
   after the first observation.

Phase 1 close-out (2026-11-09): the matcher was widened for Nepali
transliteration variance and same-named rows are split by the district named in
the hostname. Coverage rose from 659/753 (87.52%) to **712/753 (94.56%)**; the
remaining 41 unresolved local levels are absent from the directory or point at a
hostname another local level already owns. Hand-checked corrections live in
`datasets/govweb/attribution_overrides.json`, and `verify` asserts that
rejections stay unlinked and acceptances stay applied.

## Phase 3 — widen the lens past local levels (started)

The universe is hostname-first, so the local-level lens leaves most of it
unclassified. Phase 3 gives every apex hostname an owning-public-body record
with the same evidence discipline as attribution.

1. **Controlled owner vocabulary.** `owner_type` in
   `govweb/entities.py`: `local_level`, `province`, `ministry`,
   `department_or_office`, `court`, `commission`, `security_force`,
   `university_or_school`, `hospital_or_health`, `corporation_or_authority`,
   `park_or_heritage`, `media_or_culture`, `other_government`, `unknown`; with
   `owner_scope` in `{local, provincial, central, unknown}`.
2. **Ranked, offline classification.** `python -m govweb.cli entities` reads the
   committed hostname universe and classifies each apex from, in order: the
   existing local-level attribution; the curated `sources/owner_seed.json`; a
   Wikidata P856 item whose website is the apex and whose description yields a
   type. No name-only guess is made: 409 of 1,187 apexes stay `unknown` and are
   counted.
3. **Soundness.** Every classified apex carries an owner label, type, scope,
   method, evidence URL and evidence note; `verify` re-checks that entity types
   reconcile with the apex count, that `unknown` rows carry no method, and that
   local-level entity ids equal the attributed ids.
4. **Next: shrink the residual with real observation.** The 409 `unknown` apexes
   are the queue for the Phase 2 collectors extended to the full apex universe:
   root-page title, TLS certificate subject/issuer, and DNS. Each becomes an
   evidence-bearing classification rather than a name guess, and the residual
   rate becomes a reported quantity.
5. **Ceiling: whole-of-government coverage.** With every apex typed, analysis can
   report hosting/availability/dependency by `owner_scope` and `owner_type`
   first, then by district only as a secondary cut. The 753 local levels stop
   being the frame and become one lens among several.

## Phase 2 — measurement and analysis

1. **Availability as a first-class axis.** Multi-vantage collection with repeated
   probes, layered DNS → TCP → TLS → HTTP, and explicit `down`, `geo-blocked` and
   `unreachable-from-vantage` states. One vantage point lies about availability;
   the pilot's 60% timeout rate is partly a vantage artefact and must be
   separated from real outage.
2. **Provider attribution via RDAP.** Replace `ipwho.is` organisation strings
   with registry holders so concentration is attributable to a named operator.
3. **Certificate timeline.** Derive first-seen, issuer and CA-migration history
   per apex domain from the CT archive. This gives a longitudinal dimension
   without waiting for a second snapshot.
4. **Foreign edge dependency.** CDN, DNS provider, CA and third-party script
   concentration, reported with the robots-induced selection bias stated
   explicitly.
5. **Paper.** Concentration, availability, and dependency findings, with a
   responsible-disclosure appendix and a data-descriptor fallback.

## Safeguards

These carry over from `dinfra` unchanged:

- Do not bypass `robots.txt` or fetch MoFAGA pages when permission cannot be
  verified. `robots.txt` is treated as fail-closed.
- Treat Certificate Transparency results as observations, not proof of current
  municipal control or service availability.
- Do not use fuzzy matching or infer domains from municipality names.
- Keep parsing and matching offline and deterministic; run live collection only
  as a post-test step.
- TLS: one ordinary HTTPS handshake per uncached hostname, with a timeout, an
  identifying client and a configurable delay.
- HTTP: one ordinary HTTPS root-resource request per uncached hostname; response
  bodies are not consumed for the header audit.
- Hosting: ordinary DNS resolution and public IP metadata only. Never connect to
  a discovered IP address, never scan ports, never probe for vulnerabilities.
- Analysis is offline and reads existing artifacts only.
- Never present a sample as a population census, or an observation as proof of
  ownership.

## Responsible disclosure (deferred)

Before publication, notify the Department of Information Technology and MoFAGA of
the concentrated-unreachable-hostname cluster and any systemic finding, with a
response window. Do not publish a list of individually failing municipalities.
Log the notification date, recipients and response here when it happens.

**Not yet done.** This is deliberate: the build is not complete.

## Execution history

Carried over from the `dinfra` harness:

1. Canonical roster: 7 provinces, 77 districts, 765 records — complete.
2. CT discovery and exact matching: 2,091 hostnames, 0 exact municipality
   matches — complete, recorded as unresolved rather than forced.
3. TLS collector implemented and offline-tested; live collection never run.
4. HTTP header collector: 20 observations, 6 evaluable — complete.
5. Hosting/ASN classification: 20 observations — complete.
6. Third-party script inventory: 20 observations, 20/20 robots-checked —
   complete.
7. DNS/mail observations: 20 — complete.
8. `robots.txt` inventory: 20 — complete.
9. Offline analysis and reporting — complete after a transient test regression
   in the harness (SPF/DMARC unknown-state handling) was fixed.

Phase 0 port: package and dataset committed, 165 tests green, descriptor
validated, index regenerated.

Phase 1 completion:

1. `docs/plans/govweb-audit.md` scope moved to hostname-first; `dinfra` ported.
2. Roster adjudication: 12 extra records resolved with evidence.
3. Primary source replaced: local-body e-office directory (753 rows) fetched and
   committed because MoFAGA was unreachable.
4. Wikidata `P856` (1,534 items) and OSM relations (749, 5 with websites)
   committed as secondary and corroboration sources.
5. `govweb/attribution.py` implements ranked matching with hostname ownership,
   district disambiguation and non-local-slug rejection.
6. `python -m govweb.cli attribute --offline` → `attribution.json`: 659/753
   local levels (87.52%), 706 links, 94 unresolved.
7. `verify` rewritten: 17 checks, 0 failing, 1 warning (roster type split
   282/454 against the official 276/460; the split is inferred from declared
   names and is a source discrepancy, not a matching error).
8. Tidy `attribution.csv.gz` carries `evidence_url`, `evidence_note` and
   `decided_at`; `sites.csv.gz` grows to 2,782 hostnames once directory,
   Wikidata and OSM hosts join the CT inventory.
9. Gate re-checked 2026-11-09: `103.69.127.8` timed out on TCP 80 and 443.

## Known constraints

- Many `.gov.np` hosts are unreachable from outside Nepal, and the largest shared
  address is unreachable from everywhere tested. Availability must be measured
  from more than one vantage before it is interpreted.
- `robots.txt` compliance removes script data for the majority of hosts. That
  bias is a property of the study design and belongs in the paper.
- The MoFAGA directory is frequently unreachable; the local-body e-office
  directory, CT and Wikidata are the working discovery paths.
