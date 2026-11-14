"""Passive DNS resolution, TCP reachability and inverse DNS for hostnames.

Reachability is a property of a (hostname, address, port) at a moment, not a
property of a site. This collector records the raw evidence -- the resolution,
one TCP connect per address/port, and the PTR name -- so the availability claim
can be re-checked and so a failure is never silently upgraded to a result.

Collection is ordinary DNS and one TCP connect per address/port. It never scans
port ranges, never sends application data, and records a timeout as an
observation rather than as proof that a host is down.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "reachability_observations.json"
DEFAULT_TIMEOUT = 8.0
DEFAULT_PORTS = (80, 443)
DEFAULT_WORKERS = 30


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_hostname(value: str) -> str:
    value = str(value).strip().lower().rstrip(".")
    if not value or "/" in value or ":" in value or "*" in value:
        raise ValueError(f"Invalid hostname: {value!r}")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"Invalid IDNA hostname: {value!r}") from exc
    if not value.endswith(".gov.np"):
        raise ValueError(f"Only .gov.np hostnames are accepted: {value!r}")
    return value


def resolve_hostname(hostname: str, resolver=None) -> list[str]:
    """Ordinary A/AAAA resolution through the system resolver."""
    resolver = resolver or socket.getaddrinfo
    addresses: set[str] = set()
    try:
        for answer in resolver(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
            address = str(answer[4][0]).split("%", 1)[0]
            try:
                addresses.add(str(ipaddress.ip_address(address)))
            except ValueError:
                continue
    except OSError:
        return []
    return sorted(addresses)


def reverse_dns(address: str) -> str | None:
    try:
        return socket.gethostbyaddr(address)[0].rstrip(".")
    except (OSError, socket.herror, socket.gaierror):
        return None


def tcp_probe(address: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> dict:
    started = time.time()
    sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((address, port))
        return {"port": port, "state": "open", "ms": round((time.time() - started) * 1000)}
    except socket.timeout:
        return {"port": port, "state": "timeout", "ms": round(timeout * 1000)}
    except ConnectionRefusedError:
        return {"port": port, "state": "refused", "ms": round((time.time() - started) * 1000)}
    except OSError as exc:
        return {"port": port, "state": "error", "error": type(exc).__name__}
    finally:
        sock.close()


def observe_addresses(addresses: list[str], ports=DEFAULT_PORTS, timeout: float = DEFAULT_TIMEOUT,
                      workers: int = DEFAULT_WORKERS) -> list[dict]:
    def one(address: str) -> dict:
        return {
            "address": address,
            "ptr": reverse_dns(address),
            "tcp": [tcp_probe(address, port, timeout) for port in ports],
            "observed_at": timestamp(),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, addresses))


def observe_hostnames(hostnames: list[str], workers: int = DEFAULT_WORKERS) -> list[dict]:
    def one(hostname: str) -> dict:
        addresses = resolve_hostname(hostname)
        return {
            "hostname": hostname,
            "dns_status": "ok" if addresses else "no_answer",
            "addresses": addresses,
            "observed_at": timestamp(),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, hostnames))


def collect(hostnames, output: str | Path = DEFAULT_OUTPUT, *, ports=DEFAULT_PORTS,
            timeout: float = DEFAULT_TIMEOUT, workers: int = DEFAULT_WORKERS) -> dict:
    normalized = sorted({normalize_hostname(host) for host in hostnames})
    if not normalized:
        raise ValueError("No hostnames supplied for reachability collection")
    hostname_records = observe_hostnames(normalized, workers=workers)
    addresses = sorted({address for record in hostname_records for address in record["addresses"]})
    address_records = observe_addresses(addresses, ports=ports, timeout=timeout, workers=workers)
    document = {
        "schema_version": 1,
        "observation_type": "reachability",
        "source": "passive system DNS resolution, one TCP connect per address/port, inverse DNS",
        "user_agent": USER_AGENT,
        "created_at": timestamp(),
        "requested_hostname_count": len(normalized),
        "resolved_hostname_count": sum(1 for record in hostname_records if record["addresses"]),
        "address_count": len(addresses),
        "ports": list(ports),
        "timeout_seconds": timeout,
        "hostnames": hostname_records,
        "addresses": address_records,
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hostnames", nargs="+")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    document = collect(args.hostnames, args.output, timeout=args.timeout)
    print(json.dumps({"output": args.output, "hostnames": document["requested_hostname_count"],
                      "addresses": document["address_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
