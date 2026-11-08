"""Command line entry points for the govweb dataset pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from . import (
    analyze,
    attribution,
    build,
    ct_discovery,
    discover_mofaga,
    dns_mail_audit,
    hosting_audit,
    http_headers,
    paths,
    robots_audit,
    roster_fetch,
    tls_audit,
    third_party_scripts,
    verify,
)

COLLECTORS = ("tls", "headers", "hosting", "dns", "robots", "scripts")


def cmd_roster(_: argparse.Namespace) -> None:
    payload = roster_fetch.fetch_payload()
    records, province_count, district_count = roster_fetch.normalize_roster(payload)
    metadata = {
        "source_url": roster_fetch.SOURCE_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "province_count": province_count,
        "district_count": district_count,
        "municipality_count": len(records),
        "record_count": len(records),
        "normalization": (
            "Display names: surrounding and repeated whitespace collapsed; "
            "original capitalization retained. normalized_name: whitespace "
            "collapsed and Unicode case-folded. No other substitutions."
        ),
    }
    paths.DATASET_DIR.mkdir(parents=True, exist_ok=True)
    (paths.DATASET_DIR / "roster.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (paths.DATASET_DIR / "roster_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def cmd_discover_ct(args: argparse.Namespace) -> None:
    roster = json.loads((paths.DATASET_DIR / "roster.json").read_text(encoding="utf-8"))
    if args.fixture:
        records = ct_discovery.load_fixture(args.fixture)
        cache_status = "fixture"
    else:
        records, cache_status = ct_discovery.fetch_crtsh(
            paths.CACHE_DIR / "crtsh.json",
            cache_max_age=args.cache_max_age,
            timeout=args.timeout,
        )
    mapping, coverage = ct_discovery.build_outputs(roster, records, cache_status=cache_status)
    ct_discovery.write_json(paths.DATASET_DIR / "website_mappings_crtsh.json", mapping)
    ct_discovery.write_json(paths.DATASET_DIR / "website_coverage_crtsh.json", coverage)
    paths.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    (paths.SOURCE_DIR / "crtsh_gov_np.json").write_text(
        json.dumps(records, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "source": "crt.sh",
                "cache_status": cache_status,
                "roster_count": coverage["roster_count"],
                "unique_hostname_count": coverage["unique_hostname_count"],
                "mapped_count": coverage["mapped_count"],
                "unresolved_count": coverage["unresolved_count"],
                "coverage_percent": coverage["coverage_percent"],
            },
            indent=2,
        )
    )


def cmd_discover_mofaga(_: argparse.Namespace) -> None:
    mappings, coverage = discover_mofaga.discover_websites()
    print(json.dumps({"directory_rows": len(mappings), **coverage}, ensure_ascii=False))


def cmd_sample(args: argparse.Namespace) -> None:
    document = tls_audit.create_sample(
        paths.DATASET_DIR / "tls_sample.json",
        paths.DATASET_DIR / "website_mappings_crtsh.json",
        paths.CACHE_DIR / "crtsh.json",
        size=args.size,
    )
    print(json.dumps({"sample_count": document["sample_count"], "inventory_count": document["inventory_count"]}))


def cmd_collect(args: argparse.Namespace) -> None:
    paths.OBSERVATION_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = paths.DATASET_DIR / "tls_sample.json"
    selected = COLLECTORS if "all" in args.only else args.only
    if "tls" in selected:
        document = tls_audit.collect_sample(
            sample_path,
            output=paths.OBSERVATION_DIR / "tls_observations.json",
            cache_dir=paths.CACHE_DIR / "tls",
            timeout=args.timeout,
            delay_seconds=args.delay,
        )
        print(f"tls: {document['completed_count']} observations")
    if "headers" in selected:
        http_headers.collect(
            sample_path,
            paths.OBSERVATION_DIR / "http_header_observations.json",
            paths.CACHE_DIR / "http_headers",
            timeout=args.timeout,
            delay=args.delay,
        )
    if "hosting" in selected:
        hosting_audit.collect(
            sample_path,
            paths.OBSERVATION_DIR / "hosting_observations.json",
            paths.CACHE_DIR / "hosting",
            timeout=args.timeout,
            delay=args.delay,
        )
    if "dns" in selected:
        dns_mail_audit.collect(
            sample_path,
            paths.OBSERVATION_DIR / "dns_mail_observations.json",
            paths.CACHE_DIR / "dns_mail",
            timeout=args.timeout,
            delay=args.delay,
        )
    if "robots" in selected:
        robots_audit.collect(
            robots_audit.load_sample(sample_path),
            output=paths.OBSERVATION_DIR / "robots_observations.json",
            cache_dir=paths.CACHE_DIR / "robots",
            timeout=args.timeout,
            delay=args.delay,
        )
    if "scripts" in selected:
        third_party_scripts.collect(
            sample_path,
            paths.OBSERVATION_DIR / "third_party_scripts.json",
            paths.CACHE_DIR / "third_party_scripts",
            timeout=args.timeout,
            delay=args.delay,
        )


def cmd_attribute(args: argparse.Namespace) -> None:
    if args.refresh and args.offline:
        raise SystemExit("--refresh and --offline are mutually exclusive")
    if args.refresh:
        items = attribution.fetch_wikidata(timeout=args.timeout)
        attribution.write_wikidata_source(items)
    roster = attribution.load_roster()
    document = attribution.attribute(
        roster,
        attribution.load_wikidata(),
        attribution.ct_hostnames(),
        directory=attribution.load_directory(),
        osm_websites=attribution.load_osm_websites(),
        adjudication=attribution.load_adjudication(),
    )
    path = attribution.write_document(document)
    print(
        json.dumps(
            {
                "path": str(path),
                "canonical_local_levels": document["canonical_local_levels"],
                "mapped_local_levels": document["mapped_local_levels"],
                "coverage_percent": document["coverage_percent"],
                "mapping_count": document["mapping_count"],
                "methods": document["methods"],
            },
            indent=2,
        )
    )


def cmd_build(_: argparse.Namespace) -> None:
    info = build.build()
    print(json.dumps({"generated_at": info["generated_at"], "artifacts": len(info["files"])}, indent=2))


def cmd_verify(_: argparse.Namespace) -> None:
    path, report = verify.write_report()
    failing = [check for check in report["checks"] if check["status"] == "fail"]
    print(json.dumps({"report": str(path), "checks": len(report["checks"]), "failing": len(failing)}, indent=2))
    for check in report["checks"]:
        if check["status"] != "pass":
            print(f"  {check['status']}: {check['id']} — {check['detail']}")


def cmd_report(_: argparse.Namespace) -> None:
    json_path, markdown_path = analyze.write_report(paths.DATASET_DIR)
    print(json.dumps({"report": str(json_path), "summary": str(markdown_path)}, indent=2))


def cmd_status(_: argparse.Namespace) -> None:
    coverage = json.loads((paths.DATASET_DIR / "website_coverage_crtsh.json").read_text(encoding="utf-8"))
    sample = json.loads((paths.DATASET_DIR / "tls_sample.json").read_text(encoding="utf-8"))
    attribution_path = paths.DATASET_DIR / "attribution.json"
    mapped = coverage["mapped_count"]
    coverage_percent = coverage["coverage_percent"]
    if attribution_path.is_file():
        document = json.loads(attribution_path.read_text(encoding="utf-8"))
        mapped = document["mapped_local_levels"]
        coverage_percent = document["coverage_percent"]
    print(
        json.dumps(
            {
                "roster": coverage["roster_count"],
                "canonical_local_levels": 753,
                "ct_hostnames": coverage["unique_hostname_count"],
                "attributed_local_levels": mapped,
                "attribution_coverage_percent": coverage_percent,
                "observed_sample": sample["sample_count"],
                "dataset_dir": str(paths.DATASET_DIR),
                "output_dir": str(paths.OUTPUT_DIR),
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m govweb.cli",
        description="Passive observation of Nepal's .gov.np web infrastructure",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("roster", help="fetch and normalize the canonical local-level roster")
    sub.add_parser("status", help="print discovery and sample counts")

    ct = sub.add_parser("discover-ct", help="discover hostnames from Certificate Transparency")
    ct.add_argument("--fixture", help="use an offline crt.sh JSON fixture instead of the network")
    ct.add_argument("--cache-max-age", type=int, default=86400)
    ct.add_argument("--timeout", type=int, default=60)

    sub.add_parser("discover-mofaga", help="discover websites from the MoFAGA directory")

    attribute = sub.add_parser(
        "attribute",
        help="join hostnames to local levels with evidence (writes attribution.json)",
    )
    attribute.add_argument("--refresh", action="store_true", help="re-fetch the Wikidata P856 source")
    attribute.add_argument("--offline", action="store_true", help="use only committed sources (default)")
    attribute.add_argument("--timeout", type=int, default=180)

    sample = sub.add_parser("sample", help="create the deterministic observation sample")
    sample.add_argument("--size", type=int, default=20)

    collect = sub.add_parser("collect", help="run the passive collectors")
    collect.add_argument(
        "--only",
        nargs="+",
        choices=(*COLLECTORS, "all"),
        default=["all"],
        help="restrict collection to named observation types",
    )
    collect.add_argument("--timeout", type=int, default=15)
    collect.add_argument("--delay", type=float, default=1.0)

    sub.add_parser("build", help="write the tidy CSVs and build.json fingerprint")
    sub.add_parser("verify", help="write reconciliation.json and print non-passing checks")
    sub.add_parser("report", help="write audit_report.json and audit_summary.md")

    args = parser.parse_args(argv)
    dispatch = {
        "roster": cmd_roster,
        "status": cmd_status,
        "discover-ct": cmd_discover_ct,
        "discover-mofaga": cmd_discover_mofaga,
        "attribute": cmd_attribute,
        "sample": cmd_sample,
        "collect": cmd_collect,
        "build": cmd_build,
        "verify": cmd_verify,
        "report": cmd_report,
    }
    dispatch[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
