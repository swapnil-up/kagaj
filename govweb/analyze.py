from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

HEADER_NAMES = (
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)
DEFAULT_INPUTS = {
    "roster": "roster.json",
    "adjudication": "roster_adjudication.json",
    "attribution": "attribution.json",
    "entities": "entities.json",
    "coverage": "website_coverage_crtsh.json",
    "sample": "tls_sample.json",
    "tls": "observations/tls_observations.json",
    "http_headers": "observations/http_header_observations.json",
    "hosting": "observations/hosting_observations.json",
    "third_party_scripts": "observations/third_party_scripts.json",
    "dns_mail": "observations/dns_mail_observations.json",
    "robots": "observations/robots_observations.json",
}


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _observations(document: Any) -> list[dict[str, Any]]:
    if isinstance(document, dict):
        values = document.get("observations", [])
    elif isinstance(document, list):
        values = document
    else:
        return []
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _host(record: dict[str, Any], dataset: str) -> str | None:
    keys = {
        "tls": ("hostname",),
        "http_headers": ("hostname", "url"),
        "hosting": ("hostname",),
        "third_party_scripts": ("site_hostname", "hostname"),
        "dns_mail": ("site_hostname", "hostname"),
        "robots": ("hostname",),
    }.get(dataset, ("hostname",))
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            candidate = value.strip().lower().rstrip(".")
            if key == "url" and "://" in candidate:
                from urllib.parse import urlparse
                candidate = (urlparse(candidate).hostname or "").lower().rstrip(".")
            if candidate:
                return candidate
    return None


def _load_inputs(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    documents: dict[str, Any] = {}
    availability: dict[str, str] = {}
    for name, relative in DEFAULT_INPUTS.items():
        path = root / relative
        if not path.is_file():
            availability[name] = "missing"
            continue
        try:
            documents[name] = _read_json(path)
            availability[name] = "available"
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            availability[name] = "invalid"
            documents[name] = {"_load_error": str(exc)}
    return documents, availability


def _header_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    evaluable = []
    errors = 0
    for record in records:
        headers = record.get("headers")
        if record.get("error") or not isinstance(headers, dict):
            errors += 1
            continue
        normalized = {str(key).lower(): value for key, value in headers.items()}
        evaluable.append(normalized)
    present = {
        name: sum(1 for headers in evaluable if isinstance(headers.get(name.lower()), str) and bool(headers[name.lower()].strip()))
        for name in HEADER_NAMES
    }
    total_checks = len(evaluable) * len(HEADER_NAMES)
    present_checks = sum(present.values())
    return {
        "observation_count": len(records),
        "evaluable_count": len(evaluable),
        "error_or_unusable_count": errors,
        "header_names": list(HEADER_NAMES),
        "present_counts": present,
        "missing_counts": {name: len(evaluable) - count for name, count in present.items()},
        "score": round(100.0 * present_checks / total_checks, 2) if total_checks else None,
        "score_denominator": total_checks,
        "score_numerator": present_checks,
        "coverage_percent": round(100.0 * len(evaluable) / len(records), 2) if records else None,
    }


def _txt_values(record: dict[str, Any]) -> list[str]:
    records = record.get("dns_records")
    if not isinstance(records, dict):
        return []
    values = records.get("TXT", [])
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if isinstance(value, str):
            result.append(value)
        elif isinstance(value, dict):
            text = value.get("value") or value.get("text") or value.get("data")
            if isinstance(text, str):
                result.append(text)
    return result


def _query_error(record: dict[str, Any], token: str) -> bool:
    errors = record.get("errors", [])
    if isinstance(errors, dict):
        iterable = [f"{key} {value}" for key, value in errors.items()]
    elif isinstance(errors, list):
        iterable = [str(item) for item in errors]
    else:
        iterable = [str(errors)] if errors else []
    evidence = record.get("evidence", [])
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("error"):
                iterable.append(str(item.get("query_type", "")) + " " + str(item.get("query_name", "")) + " " + str(item["error"]))
    return any(token.lower() in item.lower() and ("error" in item.lower() or "fail" in item.lower()) for item in iterable)


def _mail_state(record: dict[str, Any], kind: str) -> str:
    txt = _txt_values(record)
    if kind == "spf":
        found = any("v=spf1" in value.lower() for value in txt)
        query_token = "TXT"
    else:
        dmarc_values = record.get("dmarc_txt_records", [])
        if not isinstance(dmarc_values, list):
            dmarc_values = []
        found = any("v=dmarc1" in str(value).lower() for value in dmarc_values)
        found = found or any("v=dmarc1" in value.lower() for value in txt)
        query_token = "DMARC"
    if found:
        return "present"
    # Both SPF and DMARC are TXT lookups, so a TXT query error is ambiguous
    # evidence for either one (not proof of absence).
    if _query_error(record, query_token) or _query_error(record, "TXT"):
        return "unknown"
    if record.get("status") == "error" and not record.get("dns_records"):
        return "unknown"
    # An empty completed TXT result is evidence of absence only when the record
    # does not advertise a query failure. Collector schemas without a query
    # error are treated as completed observations, with their status retained.
    if isinstance(record.get("dns_records"), dict) and isinstance(record["dns_records"].get("TXT"), list):
        return "absent"
    return "unknown"


def _dns_mail_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    states = {kind: Counter(_mail_state(record, kind) for record in records) for kind in ("spf", "dmarc")}
    both = 0
    evaluable = 0
    for record in records:
        spf = _mail_state(record, "spf")
        dmarc = _mail_state(record, "dmarc")
        if spf != "unknown" and dmarc != "unknown":
            evaluable += 1
            if spf == "present" and dmarc == "present":
                both += 1
    return {
        "observation_count": len(records),
        "spf": {state: states["spf"].get(state, 0) for state in ("present", "absent", "unknown")},
        "dmarc": {state: states["dmarc"].get(state, 0) for state in ("present", "absent", "unknown")},
        "both_present_count": both,
        "evaluable_host_count": evaluable,
        "score": round(100.0 * both / evaluable, 2) if evaluable else None,
        "score_numerator": both,
        "score_denominator": evaluable,
    }


def _dataset_summary(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"observation_count": len(records)}
    if name == "hosting":
        summary["classification_counts"] = dict(sorted(Counter(str(item.get("hosting_classification", "unknown")) for item in records).items()))
    elif name == "third_party_scripts":
        counts = [item.get("third_party_script_count") for item in records if isinstance(item.get("third_party_script_count"), int) and not isinstance(item.get("third_party_script_count"), bool)]
        summary.update({"hosts_with_count": len(counts), "third_party_script_total": sum(counts), "hosts_with_third_party_scripts": sum(value > 0 for value in counts)})
    elif name == "robots":
        summary["accessible_count"] = sum(item.get("accessible") is True for item in records)
        summary["inaccessible_or_unknown_count"] = len(records) - summary["accessible_count"]
        summary["status_counts"] = dict(sorted(Counter(str(item.get("status", "unknown")) for item in records).items()))
    elif name == "tls":
        summary["status_counts"] = dict(sorted(Counter(str(item.get("status", "unknown")) for item in records).items()))
    return summary


def analyze(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root)
    documents, availability = _load_inputs(root)
    roster = documents.get("roster", [])
    if not isinstance(roster, list):
        roster = []
    adjudication_doc = documents.get("adjudication", {})
    adjudicated_ids = {
        str(record.get("local_level_id"))
        for record in (adjudication_doc.get("records", []) if isinstance(adjudication_doc, dict) else [])
        if isinstance(record, dict) and record.get("local_level_id") is not None
    }
    active_roster_count = len(
        [record for record in roster if str(record.get("municipality_id")) not in adjudicated_ids]
    )
    attribution_doc = documents.get("attribution", {})
    attribution = attribution_doc if isinstance(attribution_doc, dict) else {}
    entities_doc = documents.get("entities", {})
    entities = entities_doc if isinstance(entities_doc, dict) else {}
    coverage = documents.get("coverage", {})
    if not isinstance(coverage, dict):
        coverage = {}
    sample_doc = documents.get("sample", {})
    sample_hosts = sample_doc.get("hostnames", []) if isinstance(sample_doc, dict) else []
    if not isinstance(sample_hosts, list):
        sample_hosts = []
    sample_hosts = sorted({str(host).strip().lower().rstrip(".") for host in sample_hosts if isinstance(host, str) and host.strip()})

    datasets = ("tls", "http_headers", "hosting", "third_party_scripts", "dns_mail", "robots")
    records_by_dataset: dict[str, list[dict[str, Any]]] = {}
    joined: dict[str, dict[str, Any]] = {host: {"hostname": host} for host in sample_hosts}
    summaries: dict[str, Any] = {}
    for name in datasets:
        records = _observations(documents.get(name)) if availability.get(name) == "available" else []
        records_by_dataset[name] = records
        summaries[name] = {
            "availability": availability.get(name, "missing"),
            **_dataset_summary(name, records),
        }
        for record in records:
            host = _host(record, name)
            if host:
                joined.setdefault(host, {"hostname": host})[name] = record

    header_score = _header_summary(records_by_dataset["http_headers"]) if availability["http_headers"] == "available" else None
    mail_score = _dns_mail_summary(records_by_dataset["dns_mail"]) if availability["dns_mail"] == "available" else None
    if header_score is not None:
        summaries["http_headers"].update(header_score)
    if mail_score is not None:
        summaries["dns_mail"].update(mail_score)
    components = {}
    if header_score and header_score["score"] is not None:
        components["http_headers"] = header_score["score"]
    if mail_score and mail_score["score"] is not None:
        components["dns_mail"] = mail_score["score"]
    combined = round(sum(components.values()) / len(components), 2) if components else None

    return {
        "schema_version": 1,
        "report_type": "passive_infrastructure_audit_analysis",
        "scope": {
            "canonical_roster_count": active_roster_count,
            "raw_roster_records": len(roster),
            "adjudicated_records": len(adjudicated_ids),
            "attribution_local_levels_mapped": attribution.get("mapped_local_levels"),
            "attribution_local_levels_unresolved": attribution.get("unresolved_local_levels"),
            "attribution_coverage_percent": attribution.get("coverage_percent"),
            "attribution_methods": attribution.get("methods"),
            "entity_apex_hostnames": entities.get("apex_hostnames"),
            "entity_classified": entities.get("classified"),
            "entity_unclassified": entities.get("unclassified"),
            "entity_by_type": entities.get("by_type"),
            "ct_unique_hostname_count": coverage.get("unique_hostname_count"),
            "ct_mapped_count": coverage.get("mapped_count"),
            "ct_unresolved_count": coverage.get("unresolved_count"),
            "ct_coverage_percent": coverage.get("coverage_percent"),
            "sample_hostnames": sample_hosts,
            "sample_count": len(sample_hosts),
            "sample_is_population_census": False,
            "municipality_hostname_join_policy": "exact_normalized_hostname_only; no municipality ownership inferred",
        },
        "input_availability": dict(sorted(availability.items())),
        "datasets": summaries,
        "scoring": {
            "method": "Mean of available HTTP security-header and DNS/mail evidence components; unavailable components excluded and identified.",
            "components": components,
            "available_component_count": len(components),
            "combined_score": combined,
            "scale": "0-100; higher means more of the specified positive configuration evidence was observed, not a security certification",
            "limitations": [
                "The 20-host sample is not a census of the 753 canonical local levels or all CT hostnames.",
                "TLS live observations are unavailable when data/tls_observations.json is absent; TLS is not scored.",
                "A missing or failed observation is not evidence of a secure configuration.",
                "Header presence does not establish policy quality or exploitability.",
                "SPF/DMARC presence does not establish policy correctness or mail deliverability.",
                "The observation sample predates attribution and contains no attributed local-level hostname.",
            ],
        },
        "hosts": [joined[host] for host in sorted(joined)],
    }


def render_markdown(report: dict[str, Any]) -> str:
    scope = report["scope"]
    scoring = report["scoring"]
    lines = [
        "# govweb Passive Infrastructure Audit Summary",
        "",
        "## Scope and coverage",
        "",
        f"- Canonical local levels in roster: **{scope['canonical_roster_count']}**",
        f"- Local levels with an attributed hostname: **{scope.get('attribution_local_levels_mapped', 'unavailable')}**"
        f" ({scope.get('attribution_coverage_percent', 'unavailable')}%), "
        f"{scope.get('attribution_local_levels_unresolved', 'unavailable')} unresolved",
        f"- Apex hostnames with an entity classification: **{scope.get('entity_classified', 'unavailable')}**"
        f" of {scope.get('entity_apex_hostnames', 'unavailable')}"
        f" ({scope.get('entity_unclassified', 'unavailable')} unknown)",
        f"- Distinct CT-derived hostnames: **{scope.get('ct_unique_hostname_count', 'unavailable')}**"
        f" (the merged universe adds attribution-sourced hostnames on top)",
        f"- CT mapped entries: **{scope.get('ct_mapped_count', 'unavailable')}**",
        f"- CT unresolved entries: **{scope.get('ct_unresolved_count', 'unavailable')}**",
        f"- Observed hostname sample: **{scope['sample_count']}** (not a population census)",
        "",
        "Hostnames are joined across datasets only by exact normalized hostname. No municipal ownership is inferred from a hostname.",
        "",
        "## Dataset availability and observations",
        "",
        "| Dataset | Availability | Observations |",
        "|---|---:|---:|",
    ]
    for name, summary in report["datasets"].items():
        lines.append(f"| {name} | {summary['availability']} | {summary.get('observation_count', 0)} |")
    lines.extend(["", "## Security evidence scores", ""])
    for name, score in scoring["components"].items():
        lines.append(f"- {name}: **{score:.2f}/100**")
    if scoring["combined_score"] is None:
        lines.append("- Combined score: **not available** (no component had an evaluable denominator)")
    else:
        lines.append(f"- Combined score: **{scoring['combined_score']:.2f}/100**")
    lines.extend([
        "",
        "Scores are descriptive evidence indicators, not certifications, vulnerability assessments, or municipality rankings. The HTTP component measures presence of six audited headers across usable responses. The DNS/mail component measures the share of evaluable hosts with both SPF and DMARC evidence. Each component's numerator, denominator, and coverage are in the JSON report.",
        "",
        "## Key observations",
        "",
    ])
    http = report["datasets"].get("http_headers", {})
    if http.get("availability") == "available":
        lines.append(f"- HTTP header observations: {http.get('observation_count', 0)}; evaluable responses: {http.get('evaluable_count', 0)}; collection errors or unusable records: {http.get('error_or_unusable_count', 0)}.")
    dns = report["datasets"].get("dns_mail", {})
    if dns.get("availability") == "available":
        lines.append(f"- DNS/mail observations: {dns.get('observation_count', 0)}; hosts with both SPF and DMARC evidence: {dns.get('both_present_count', 0)} of {dns.get('evaluable_host_count', 0)} evaluable hosts.")
    hosting = report["datasets"].get("hosting", {})
    if hosting.get("availability") == "available":
        lines.append(f"- Hosting classifications: {json.dumps(hosting.get('classification_counts', {}), sort_keys=True)}.")
    scripts = report["datasets"].get("third_party_scripts", {})
    if scripts.get("availability") == "available":
        lines.append(f"- Third-party scripts recorded: {scripts.get('third_party_script_total', 0)} across {scripts.get('hosts_with_count', 0)} hosts with a numeric count.")
    robots = report["datasets"].get("robots", {})
    if robots.get("availability") == "available":
        lines.append(f"- robots.txt accessible observations: {robots.get('accessible_count', 0)} of {robots.get('observation_count', 0)}.")
    tls = report["datasets"].get("tls", {})
    if tls.get("availability") != "available":
        lines.append("- TLS live observations: unavailable; no TLS score is assigned.")
    lines.extend(["", "## Limitations", ""])
    for limitation in scoring["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


def write_report(root: str | Path = ".") -> tuple[Path, Path]:
    root = Path(root)
    report = analyze(root)
    json_path = root / "audit_report.json"
    markdown_path = root / "audit_summary.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    md_tmp = markdown_path.with_suffix(markdown_path.suffix + ".tmp")
    json_tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_tmp.write_text(render_markdown(report), encoding="utf-8")
    json_tmp.replace(json_path)
    md_tmp.replace(markdown_path)
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze existing govweb observation artifacts offline")
    parser.add_argument("--root", default=".", help="dataset directory holding the observation artifacts")
    parser.add_argument("--json-out", default="audit_report.json")
    parser.add_argument("--markdown-out", default="audit_summary.md")
    args = parser.parse_args(argv)
    root = Path(args.root)
    report = analyze(root)
    json_path = root / args.json_out
    markdown_path = root / args.markdown_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
