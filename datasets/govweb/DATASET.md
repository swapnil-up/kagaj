# Dataset — Nepal `.gov.np` web-infrastructure observations

Passive observations of Nepal's public-sector web infrastructure. Nothing here
comes from a port scan, a vulnerability probe, or an exploit attempt: every row
is derived from an ordinary DNS lookup, an ordinary TLS handshake, one HTTPS
request for response headers, a published `robots.txt`, or a public
Certificate Transparency response.

## What this dataset is — and is not

**Is:** a reproducible inventory of 2,837 `.gov.np` hostnames, an
evidence-bearing attribution of those hostnames to 753 local levels, a small set
of per-hostname measurements over a pilot sample, and the canonical local-level
roster.

**Is not:** a census of the 753 local levels' sites, a security assessment, a
ranking of municipalities, or proof that a hostname belongs to a particular
local government. Attribution records the strongest available source agreement
and names that source; where sources disagree or are missing, the local level is
left unresolved rather than guessed.

Read `audit_summary.md` and `reconciliation.json` before using any figure.

## Grain

| Table | One row is |
|---|---|
| `sites.csv.gz` | a discovered `.gov.np` hostname |
| `entities.csv.gz` | a discovered apex hostname and its classified owning public body, or `unknown` |
| `roster.csv.gz` | a local level as declared by the OAG API |
| `attribution.csv.gz` | a local level with its linked hostname, or an unresolved local level with an empty hostname |
| `hosting.csv.gz` | one hosting observation of one hostname |
| `dns_mail.csv.gz` | one DNS/mail observation of one hostname |
| `http_headers.csv.gz` | one root-resource header observation of one hostname |
| `tls.csv.gz` | one TLS handshake observation of one hostname |
| `third_party_scripts.csv.gz` | one referenced script, or one empty-script row per unfetched hostname |
| `robots.csv.gz` | one `robots.txt` observation of one hostname |

The unit is a hostname. Joining by local level requires going through
`attribution.csv.gz`; do not invent that link from a name. One local level can
carry more than one hostname (apex plus a legacy or campaign domain), so the
attribution table has one row per accepted link.

## Coverage (2026-11-09 snapshot)

| Quantity | Value |
|---|---:|
| Roster records | 765 |
| Adjudicated (excluded) records | 12 |
| Canonical local levels | 753 |
| Local levels with at least one attributed hostname | 712 |
| Attribution coverage | 94.56% |
| Accepted hostname links | 761 |
| Unresolved local levels | 41 |
| Distinct discovered hostnames | 2,837 |
| Distinct apex hostnames | 1,187 |
| Hostnames in observation sample | 20 |

Attribution methods, by accepted hostname link:

| Method | Links |
|---|---:|
| `localbody_directory` | 682 |
| `wikidata_p856` | 65 |
| `ct_hostname_slug` | 13 |
| `manual` | 1 |

Entity classification reaches past the local-level roster to every apex in the
discovered universe (1,187 apexes):

| Owner type | Apexes |
|---|---:|
| `local_level` | 758 |
| `ministry` | 5 |
| `other_government` | 4 |
| `media_or_culture` | 3 |
| `park_or_heritage` | 3 |
| `department_or_office` | 2 |
| `province` | 2 |
| `commission` | 1 |
| `unknown` | 409 |

`unknown` is the honest residual: no committed source names an owner, so the
apex is counted rather than guessed. Those 409 apexes are the queue for the
Phase 2 root-title and certificate-subject collection.

The roster is 12 records larger than the official count. `roster_adjudication.json`
records each excluded record with a status (`superseded`, `duplicate` or
`misplaced`), the superseding roster id, and evidence. `reconciliation.json`
re-checks the arithmetic rather than deleting rows to force a match.

## Method

1. **Roster.** `python -m govweb.cli roster` reads the OAG local-level report
   API and normalizes whitespace and case only.
2. **Discovery.** `python -m govweb.cli discover-ct` extracts DNS names from the
   `name_value` and `common_name` fields of a crt.sh response and discards
   anything outside `.gov.np`.
3. **Attribution.** `python -m govweb.cli attribute` matches the canonical roster
   against four committed sources in fixed rank order:

   | Rank | Method | Source |
   |---:|---|---|
   | 1 | `manual` | adjudicated decision recorded in the engine |
   | 2 | `localbody_directory` | local-body e-office directory (753 rows, 750 websites) |
   | 3 | `wikidata_p856` | Wikidata P856 official website, name + district agreement |
   | 4 | `ct_hostname_slug` | crt.sh hostname whose slug matches the gazetted name |
   | 5 | `osm_website` | OSM `website` tag, corroboration only |

   A directory row is accepted only when its hostname is a plausible local-level
   `.gov.np` name, is not a blocked agency/province slug, and is not already
   claimed by another local level. Ties between same-named local levels are
   broken by district or hostname agreement; if that still leaves two
   candidates, the row is dropped and the local level stays unresolved. Every
   accepted row carries `method`, `confidence`, `evidence_url`, `evidence_note`
   and `decided_at`. Manual corrections live in `attribution_overrides.json`
   (`reject` or `accept`) with their own reason and evidence, rather than as
   hidden matcher tweaks.
4. **Entities.** `python -m govweb.cli entities` classifies every discovered
   apex hostname into an owning public body. Rank order: an existing local-level
   attribution (inherited); the curated `sources/owner_seed.json`; then a
   Wikidata P856 item whose website is the apex and whose description yields a
   government owner type. A description like "football club" is left `unknown`;
   so is any apex with no committed source. Every classified row keeps the owner
   label, type, scope, method, evidence URL and evidence note.
5. **Sample.** `python -m govweb.cli sample` takes the lexicographically first
   unique hostnames from the discovered inventory. Hostnames are never
   synthesized. The sample predates attribution and is not municipality-weighted.
6. **Collection.** `python -m govweb.cli collect` performs one observation per
   hostname per collector, with a 7-day per-host cache and atomic incremental
   persistence. Network failures are retained as observations.
7. **Analysis.** `python -m govweb.cli report` reads only committed artifacts
   and performs no network requests.
8. **Fingerprint.** `python -m govweb.cli build` writes the tidy CSVs and
   `build.json`; `python -m govweb.cli verify` writes `reconciliation.json`.

## Interpretation rules

- A missing header, a failed handshake, or an absent SPF record is a **missing
  observation**, not proof of an insecure configuration. The analyzer reports
  denominators and excludes unevaluable hosts from scores.
- An attribution is a source agreement, not proof of ownership. Read
  `method` and `evidence_url` before treating a link as authoritative.
- An entity type is a source agreement too. `unknown` means no committed source
  names an owner, never that the site is private or unofficial.
- Unresolved local levels mean the sources did not supply a usable hostname. They
  are not evidence that the local level has no website.
- Country-level geolocation is approximate. It does not establish physical server
  location, legal hosting provider, or municipal ownership.
- `robots_disallowed` rows carry zero scripts because the page was deliberately
  not fetched. That is a collection decision, not a finding about the site.
- Scores in `audit_report.json` are descriptive evidence indicators. They are not
  certifications and must not be used to rank local governments.

## Known issues

- The 20-hostname observation sample was drawn before attribution and contains
  no attributed local-government hostname. Phase 2 of
  `docs/plans/govweb-audit.md` replaces it with a tiered sample drawn from the
  attributed universe.
- The live TLS collection has not run, so `tls.csv.gz` is header-only. The
  analyzer reports TLS as unavailable and assigns it no score.
- 60% of the pilot sample disallows the crawler in `robots.txt`, so script
  inventory is available for only a permissive minority; this selection bias is
  structural and must be reported with any script finding.
- The local-body directory has data-quality problems: duplicate rows with the
  same website, wrong or generic links (for example a Rajbiraj row pointing at
  `rajapurmun.gov.np`), and hosts that do not resolve. The matcher rejects links
  that do not corroborate the roster name, and hand-checked rejections and
  acceptances are recorded in `attribution_overrides.json`; every remaining
  unresolved local level is either absent from the directory or points at a
  hostname already owned by another local level.
- `laligurans.gov.np`, `mahakulung.gov.np` and `myanglung.gov.np` do not resolve
  in DNS and are therefore absent from the discovered inventory even though the
  directory lists them.
- The MoFAGA local-contact directory was unreachable during collection and is no
  longer used; the e-office directory replaced it as the primary attribution
  source.
