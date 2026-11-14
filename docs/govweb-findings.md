# govweb findings — 2026-11-09

Read-only and passive throughout. Everything is reproducible from the committed
`datasets/govweb/` artifacts; the commands are in `datasets/govweb/DATASET.md`.

## 1. The municipal slice resolves into a handful of addresses

Attribution yields 761 hostnames for 712 of 753 local levels.

| Quantity | Value |
|---|---:|
| Attributed hostnames | 761 |
| Resolve | 727 (95.5%) |
| Distinct IPv4 addresses | **12** |
| In `103.69.0.0/16` | 717 (98.6%) |
| Single address `103.69.124.140` | 421 (57.9%) |
| Top /24 `103.69.124.0/24` | 422 (58.0%) |

RDAP (`operators.csv.gz`) names the holders: `103.69.124.0–103.69.127.255` is
**DOITGON-NP** (Department of Information Technology); `202.45.144.0/22` is
**NITC-NP** (National Information Technology Center). Foreign hosts are single
outliers (20i/GB, Hetzner, Contabo, HostGator/DIMENOC, NTHL).

## 2. Whole-space entity join

`entity_hosting.csv.gz` joins every apex (1,187) to its owner type and its
observed reachability. Local-level apexes: 150 reachable, 577 `timeout`, 31
`no_dns`. Across the whole space: 284 reachable, 783 `timeout`, 98 `no_dns`, 21
`unknown`, 1 `refused`.

## 3. Reachability, and why one vantage was not enough

From the primary vantage (inside Nepal, Nepal Telecom / NTC):

| Address | Municipal hosts | TCP 80/443 |
|---|---:|---|
| `103.69.124.140` | 421 | timeout |
| `103.69.127.8` | 153 | timeout |
| `103.69.127.59` | 143 | open ~6 ms |
| `103.69.124.56` | 1 | open |

The control IPs `1.1.1.1`/`8.8.8.8` answer, so the timeout is selective. From
one vantage that is not yet a finding — so the same hosts were measured through
the public **Globalping** probe network (`globalping.csv.gz`):

| Host (address) | NP (2nd ISP) | IN | DE |
|---|---|---|---|
| `aadarshakotwalmun` (`.124.140`) | TCP timeout | TCP timeout | TCP timeout |
| `baglungmun` (`.127.8`) | TCP timeout | TCP timeout | TCP timeout |
| `amargadhimun` (`.127.59`) | TCP ok, TLS reset | TCP ok, TLS reset | TCP ok, TLS reset |
| `kathmandu` (`.124.56`) | HTTP 307 | TLS reset | HTTP 307 |

The Nepal Globalping probe is a *different* ISP — Kathmandu, AS45424, Himalayan
Online Services (eyeball network). `103.69.124.140` and `103.69.127.8` time out
from all three independent vantages, so the failure follows the **destination**,
not the observer. The `.59`/`.56` resets show the estate is also inconsistent by
vantage and failure mode.

**Claim this supports:** hosts on `103.69.124.140` and `103.69.127.8` accept no
TCP connection on 80/443 from three independent vantages; 574 of the 727
resolved municipal hostnames (78.9%) and 574 of 758 local-level apexes sit on
one of those two addresses. It does **not** yet support
"offline to citizens" for a named municipality; that needs a designed sample and
repeats.

## 4. Current TLS (live, 150 reachable hosts)

This was a one-off pass whose raw artifact was not committed, so treat these
numbers as a lead to verify, not as a reproducible result; `tls.csv.gz` is still
header-only.

- 147 Let's Encrypt, 2 DigiCert, 1 Sectigo; all TLS 1.3.
- Only 1 of 150 certificates carries an Organization name, so certificates
  cannot drive the entity layer.
- 27 hostname-mismatch verification failures, 25 of them on the single shared,
  reachable address `103.69.127.59` (~17% of its hosts). Descriptive, not an
  exploit.

## 5. Certificate Transparency

The committed CT source is a stale 2011–2018 snapshot. A fresh crt.sh
`%.gov.np` query returned the identical set and then rate-limited; crt.sh is not
returning current data for this query. Cert Spotter confirms current issuance
exists (for example `kathmandu.gov.np`, 75 certs through 2026-11-07). Any
certificate-timeline analysis is blocked until the CT source is replaced.

## 6. Inverse DNS

`103.69.124.56` is `p4.gcloud.gov.np` (a naming lead on the DOIT block),
`202.45.144.235` is `144-235.nitc.gov.np`; the three highest-traffic addresses
carry no PTR. Foreign PTRs are commodity hosting.

## 7. Data quality

34 attributed municipal hostnames do not resolve (`mun`-prefixed mangles,
legacy short names, malformed suffixes). The local-body directory contains
duplicate and wrong links, handled by `attribution_overrides.json`.

## What is not established

- A per-municipality availability claim; the multi-vantage matrix is a
  three-vantage sample, not a designed census, and needs repetition.
- Any current certificate-timeline claim (stale CT).
- Operator identity beyond the RDAP allocation holder: `DOITGON-NP` is who the
  block is registered to, not necessarily who runs each server.

## Responsible disclosure

Per `docs/plans/govweb-audit.md`, findings are aggregate/structural only. No
per-municipality failure list is published before notifying DOIT and MoFAGA with
a response window.
