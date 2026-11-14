"""RDAP registry attribution for observed addresses.

An address is not an operator. This module resolves each observed address to the
*registry allocation holder* through RDAP, so a concentration finding can name
an organization rather than an IP. It records the holder, country, allocation
range and allocation type, and never infers an operator from a name.

Queries go to the public RDAP bootstrap (rdap.org), which redirects to the
responsible RIR. One request per address; no other network activity.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
RDAP_BOOTSTRAP = "https://rdap.org/ip/"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "rdap_observations.json"
DEFAULT_TIMEOUT = 20.0
DEFAULT_WORKERS = 4
DEFAULT_ATTEMPTS = 4
DEFAULT_BACKOFF = 1.5


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _remarks(document: dict) -> str:
    parts = []
    for remark in document.get("remarks", []) or []:
        if isinstance(remark, dict):
            parts.extend(remark.get("description", []) or [])
    return " ".join(str(part) for part in parts).strip()[:300]


def lookup(address: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    record = {"address": address, "status": "error", "observed_at": timestamp()}
    try:
        record["address"] = str(ipaddress.ip_address(address))
    except ValueError:
        record["error"] = "invalid_address"
        return record
    request = urllib.request.Request(
        RDAP_BOOTSTRAP + record["address"],
        headers={"accept": "application/rdap+json", "user-agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            document = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        record["error"] = type(exc).__name__
        return record
    handle = document.get("handle")
    entities = document.get("entities", []) or []
    registrant = next(
        (entity.get("handle") for entity in entities if "registrant" in (entity.get("roles") or [])),
        None,
    )
    record.update(
        {
            "status": "observed",
            "name": document.get("name"),
            "handle": handle,
            "registrant_handle": registrant,
            "country": document.get("country"),
            "type": document.get("type"),
            "start_address": document.get("startAddress"),
            "end_address": document.get("endAddress"),
            "cidr": _network(document.get("startAddress"), document.get("endAddress")),
            "remarks": _remarks(document),
        }
    )
    return record


def _network(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    try:
        networks = list(ipaddress.summarize_address_range(ipaddress.ip_address(start), ipaddress.ip_address(end)))
    except (ValueError, TypeError):
        return None
    return ", ".join(str(network) for network in networks[:4]) if networks else None


def collect(addresses, output: str | Path = DEFAULT_OUTPUT, *, timeout: float = DEFAULT_TIMEOUT,
            workers: int = DEFAULT_WORKERS, attempts: int = DEFAULT_ATTEMPTS,
            backoff: float = DEFAULT_BACKOFF) -> dict:
    unique = sorted({str(address) for address in addresses})
    if not unique:
        raise ValueError("No addresses supplied for RDAP collection")

    def one(address: str) -> dict:
        record = lookup(address, timeout=timeout)
        for attempt in range(1, attempts):
            if record["status"] == "observed":
                break
            time.sleep(backoff * attempt)
            record = lookup(address, timeout=timeout)
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(one, unique))
    document = {
        "schema_version": 1,
        "observation_type": "rdap",
        "source": "RDAP bootstrap (rdap.org) allocation metadata",
        "user_agent": USER_AGENT,
        "created_at": timestamp(),
        "requested_address_count": len(unique),
        "observed_address_count": sum(1 for record in records if record["status"] == "observed"),
        "observations": records,
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addresses", nargs="+")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    document = collect(args.addresses, args.output, timeout=args.timeout)
    print(json.dumps({"output": args.output, "observed": document["observed_address_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
