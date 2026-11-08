# govweb Passive Infrastructure Audit Summary

## Scope and coverage

- Canonical local levels in roster: **753**
- Local levels with an attributed hostname: **659** (87.52%), 94 unresolved
- Distinct CT hostnames: **2091**
- CT mapped entries: **0**
- CT unresolved entries: **765**
- Observed hostname sample: **20** (not a population census)

Hostnames are joined across datasets only by exact normalized hostname. No municipal ownership is inferred from a hostname.

## Dataset availability and observations

| Dataset | Availability | Observations |
|---|---:|---:|
| tls | missing | 0 |
| http_headers | available | 20 |
| hosting | available | 20 |
| third_party_scripts | available | 20 |
| dns_mail | available | 20 |
| robots | available | 20 |

## Security evidence scores

- http_headers: **22.22/100**
- dns_mail: **15.00/100**
- Combined score: **18.61/100**

Scores are descriptive evidence indicators, not certifications, vulnerability assessments, or municipality rankings. The HTTP component measures presence of six audited headers across usable responses. The DNS/mail component measures the share of evaluable hosts with both SPF and DMARC evidence. Each component's numerator, denominator, and coverage are in the JSON report.

## Key observations

- HTTP header observations: 20; evaluable responses: 6; collection errors or unusable records: 14.
- DNS/mail observations: 20; hosts with both SPF and DMARC evidence: 3 of 20 evaluable hosts.
- Hosting classifications: {"Nepal-local": 12, "foreign-other": 3, "unknown": 5}.
- Third-party scripts recorded: 2 across 20 hosts with a numeric count.
- robots.txt accessible observations: 5 of 20.
- TLS live observations: unavailable; no TLS score is assigned.

## Limitations

- The 20-host sample is not a census of the 753 canonical local levels or all CT hostnames.
- TLS live observations are unavailable when data/tls_observations.json is absent; TLS is not scored.
- A missing or failed observation is not evidence of a secure configuration.
- Header presence does not establish policy quality or exploitability.
- SPF/DMARC presence does not establish policy correctness or mail deliverability.
- The observation sample predates attribution and contains no attributed local-level hostname.
