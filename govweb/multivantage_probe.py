#!/usr/bin/env python3
"""Passive multi-vantage reachability probe for the govweb study.

Run this on a machine on a *different* network path from the primary host
(ideally a host inside Nepal on a non-DOIT ISP, and/or an external VPS) and
return the JSON. It only opens one TCP connection per address/port and reads
one HTTPS root resource for a few hostnames. No scanning, no exploits.

    python3 multivantage_probe.py --label "nepal-worldlink" > result.json

Requires only the standard library and outbound TCP. If `traceroute` or `mtr`
is installed it is used read-only to locate where a path stops.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import subprocess
import sys
import time
from urllib.request import Request, urlopen

# The addresses that carry ~99% of attributable municipal websites.
ADDRESSES = [
    "103.69.124.140",  # DOITGON-NP, 421 hostnames, timed out from primary
    "103.69.127.8",    # DOITGON-NP, 152 hostnames, timed out from primary
    "103.69.127.59",   # DOITGON-NP, 143 hostnames, open from primary
    "103.69.124.56",   # DOITGON-NP, open from primary
    "202.45.144.235",  # NITC-NP, timed out from primary
    "1.1.1.1",         # control: must always answer
]
PORTS = (80, 443)

# One representative hostname per address, for an HTTPS identity check.
HOSTNAMES = [
    "lalitpurmun.gov.np",
    "kathmandu.gov.np",
    "bhaktapurmun.gov.np",
    "pokharamun.gov.np",
    "hetaudamun.gov.np",
]

UA = "kagaj-govweb/0.1 (research; passive reachability check; contact: kagaj)"


def tcp(ip: str, port: int, timeout: float) -> dict:
    started = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((ip, port))
        return {"ip": ip, "port": port, "state": "open", "ms": round((time.time() - started) * 1000)}
    except socket.timeout:
        return {"ip": ip, "port": port, "state": "timeout", "ms": round(timeout * 1000)}
    except OSError as exc:
        return {"ip": ip, "port": port, "state": type(exc).__name__, "errno": exc.errno}
    finally:
        sock.close()


def fetch_title(host: str, timeout: float) -> dict:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    record = {"hostname": host}
    try:
        record["ip"] = socket.gethostbyname(host)
    except OSError as exc:
        record["dns"] = type(exc).__name__
        return record
    for scheme in ("https", "http"):
        try:
            req = Request(f"{scheme}://{host}/", headers={"User-Agent": UA})
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                body = resp.read(30000).decode("utf-8", "replace")
                record["status"] = resp.status
                record["scheme"] = scheme
                record["server"] = resp.headers.get("Server", "")
                record["title"] = _title(body)
                return record
        except Exception as exc:  # noqa: BLE001 - record whatever happened
            record["error"] = f"{scheme}: {type(exc).__name__}"
    return record


def _title(body: str) -> str:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    return match.group(1).strip()[:120] if match else ""


def traceroute(ip: str, timeout: float) -> str:
    for tool in ("mtr", "traceroute"):
        try:
            if tool == "mtr":
                out = subprocess.run(
                    ["mtr", "-r", "-c", "3", "-T", "-P", "443", ip],
                    capture_output=True, text=True, timeout=timeout,
                )
            else:
                out = subprocess.run(
                    ["traceroute", "-T", "-p", "443", "-w", "2", "-q", "1", ip],
                    capture_output=True, text=True, timeout=timeout,
                )
            return out.stdout.strip()[-1500:]
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="name this vantage, e.g. nepal-worldlink")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--no-traceroute", action="store_true")
    args = parser.parse_args()

    result = {
        "label": args.label,
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "egress_ip": _egress_ip(),
        "tcp": [],
        "http": [],
        "traceroute": {},
    }
    for ip in ADDRESSES:
        for port in PORTS:
            result["tcp"].append(tcp(ip, port, args.timeout))
    for host in HOSTNAMES:
        result["http"].append(fetch_title(host, args.timeout))
    if not args.no_traceroute:
        for ip in ADDRESSES:
            if ip == "1.1.1.1":
                continue
            trace = traceroute(ip, args.timeout + 30)
            if trace:
                result["traceroute"][ip] = trace
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _egress_ip() -> str:
    try:
        with urlopen("https://api.ipify.org", timeout=8) as resp:
            return resp.read().decode().strip()
    except Exception:  # noqa: BLE001
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
