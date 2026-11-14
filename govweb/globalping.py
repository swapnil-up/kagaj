"""Multi-vantage measurements through the public Globalping network.

One vantage cannot tell an outage from a path failure. Globalping exposes a
global pool of community probes; a measurement is executed from probes in named
countries, which gives independent vantages without owning them. Results are
recorded verbatim, including the probe location and network, so a reachability
claim can be attributed to a named vantage.

Only ordinary measurements are issued (HTTP/DNS/ping), against already
discovered hostnames or addresses, at low volume, with a delay between calls.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
API = "https://api.globalping.io/v1"
# A second Nepali eyeball ISP plus regional and intercontinental controls.
DEFAULT_LOCATIONS = ("NP", "IN", "DE", "US")
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "globalping_observations.json"
DEFAULT_TIMEOUT = 30.0
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_POLL_ATTEMPTS = 20
DEFAULT_DELAY = 2.0


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _request(url: str, payload: dict | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"content-type": "application/json", "accept": "application/json", "user-agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def create_measurement(kind: str, target: str, country: str, limit: int = 1) -> dict:
    return _request(
        f"{API}/measurements",
        {"type": kind, "target": target, "locations": [{"country": country}], "limit": limit},
    )


def wait_measurement(identifier: str, attempts: int = DEFAULT_POLL_ATTEMPTS,
                     interval: float = DEFAULT_POLL_SECONDS) -> dict:
    for _ in range(attempts):
        document = _request(f"{API}/measurements/{identifier}")
        if document.get("status") == "finished":
            return document
        time.sleep(interval)
    return document


def normalize(document: dict, requested_country: str) -> list[dict]:
    records = []
    for result in document.get("results", []) or []:
        probe = result.get("probe") or {}
        location = probe.get("location") or {}
        outcome = result.get("result") or {}
        timing = outcome.get("timings") or {}
        records.append(
            {
                "target": document.get("target"),
                "measurement_type": document.get("type"),
                "requested_country": requested_country,
                "country": location.get("country") or requested_country,
                "city": location.get("city"),
                "asn": location.get("asn"),
                "network": location.get("network"),
                "status_code": outcome.get("statusCode"),
                "resolved_address": outcome.get("resolvedAddress"),
                "tcp_ms": timing.get("tcp"),
                "tls_ms": timing.get("tls"),
                "total_ms": timing.get("total"),
                "raw_output": str(outcome.get("rawOutput") or "")[:400],
                "observed_at": timestamp(),
            }
        )
    return records


def measure(kind: str, target: str, countries=DEFAULT_LOCATIONS, *, limit: int = 1,
            delay: float = DEFAULT_DELAY) -> list[dict]:
    records = []
    for index, country in enumerate(countries):
        if index and delay:
            time.sleep(delay)
        try:
            created = create_measurement(kind, target, country, limit=limit)
        except urllib.error.HTTPError as exc:
            records.append({"target": target, "requested_country": country, "measurement_type": kind,
                            "error": f"HTTP {exc.code}", "observed_at": timestamp()})
            continue
        document = wait_measurement(created["id"])
        records.extend(normalize(document, country))
    return records


def collect(targets, countries=DEFAULT_LOCATIONS, output: str | Path = DEFAULT_OUTPUT, *,
            kind: str = "http", limit: int = 1, delay: float = DEFAULT_DELAY) -> dict:
    observations: list[dict] = []
    for index, target in enumerate(targets):
        if index and delay:
            time.sleep(delay)
        observations.extend(measure(kind, target, countries=countries, limit=limit, delay=delay))
    document = {
        "schema_version": 1,
        "observation_type": "globalping",
        "source": "Globalping public probe network (https://globalping.io)",
        "user_agent": USER_AGENT,
        "created_at": timestamp(),
        "measurement_type": kind,
        "requested_countries": list(countries),
        "targets": list(targets),
        "observations": observations,
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("targets", nargs="+", help="hostnames or addresses to measure")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--type", default="http", choices=("http", "ping", "dns", "traceroute", "mtr"))
    parser.add_argument("--locations", nargs="+", default=list(DEFAULT_LOCATIONS))
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)
    document = collect(args.targets, countries=args.locations, output=args.output,
                       kind=args.type, limit=args.limit, delay=args.delay)
    print(json.dumps({"output": args.output, "observations": len(document["observations"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
