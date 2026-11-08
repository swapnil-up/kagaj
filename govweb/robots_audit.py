import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_SAMPLE = paths.DATASET_DIR / "tls_sample.json"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "robots_observations.json"
DEFAULT_CACHE = paths.CACHE_DIR / "robots"
DEFAULT_TIMEOUT = 15
DEFAULT_DELAY = 1.0
DEFAULT_TTL_HOURS = 168
MAX_ROBOTS_BYTES = 1024 * 1024
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    value = value or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_hostname(value):
    value = str(value).strip().lower().rstrip(".")
    if not value or "/" in value or ":" in value or "*" in value or "\\" in value:
        raise ValueError("Invalid hostname")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid IDNA hostname") from exc
    if not value.endswith(".gov.np"):
        raise ValueError("Only discovered .gov.np hostnames are accepted")
    labels = value.split(".")
    if any(not label or len(label) > 63 or not _HOST_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Invalid DNS hostname")
    if len(value) > 253:
        raise ValueError("Invalid DNS hostname length")
    return value


def load_sample(path=DEFAULT_SAMPLE):
    with Path(path).open(encoding="utf-8") as handle:
        document = json.load(handle)
    values = document.get("hostnames") if isinstance(document, dict) else None
    if not isinstance(values, list):
        raise ValueError("TLS sample must contain a hostnames list")
    result = sorted({normalize_hostname(item) for item in values})
    if len(result) > 20:
        raise ValueError("Robots audit is limited to the existing 20-host sample")
    return result


def cache_key(hostname):
    return hashlib.sha256(hostname.encode("utf-8")).hexdigest()


def read_cache(path, ttl_hours=DEFAULT_TTL_HOURS):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(payload["cached_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            return None
        age = utc_now() - observed.astimezone(timezone.utc)
        if age < timedelta(0) or age > timedelta(hours=ttl_hours):
            return None
        return payload.get("value")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return None


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_cache(path, value):
    atomic_write_json(path, {"cached_at": timestamp(), "value": value})


def parse_robots(text):
    """Parse robots.txt groups, preserving directive order and empty values."""
    groups = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name == "user-agent":
            if current is None or current["directives"]:
                current = {"user_agents": [], "directives": []}
                groups.append(current)
            current["user_agents"].append(value)
        elif current is not None:
            current["directives"].append({"directive": name, "value": value})
    return groups


def _base_observation(hostname, status, status_code=None, accessible=False,
                      final_url=None, directives=None, evidence=None,
                      confidence="high", error=None):
    robots_url = f"https://{hostname}/robots.txt"
    return {
        "hostname": hostname,
        "robots_url": robots_url,
        "accessible": accessible,
        "status_code": status_code,
        "directives": directives or [],
        "status": status,
        "evidence": evidence or {},
        "confidence": confidence,
        "observed_at": timestamp(),
        "source_url": robots_url,
        "final_url": final_url,
        "error": error,
    }


def fetch_robots(hostname, timeout=DEFAULT_TIMEOUT, opener=None):
    hostname = normalize_hostname(hostname)
    robots_url = f"https://{hostname}/robots.txt"
    request = urllib.request.Request(
        robots_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*;q=0.1"},
    )
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=timeout) as response:
            status_code = getattr(response, "status", None)
            if status_code is None:
                status_code = response.getcode()
            final_url = response.geturl()
            parsed = urlparse(final_url)
            try:
                final_host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
                final_port = parsed.port
            except (UnicodeError, ValueError):
                final_host = ""
                final_port = -1
            if (parsed.scheme.lower() != "https" or final_host != hostname
                    or final_port not in (None, 443) or parsed.username is not None
                    or parsed.password is not None):
                return _base_observation(
                    hostname,
                    "error",
                    status_code=status_code,
                    final_url=final_url,
                    evidence={"redirect_rejected": True},
                    confidence="low",
                    error="Robots resource redirected outside the original HTTPS host",
                )
            if status_code != 200:
                return _base_observation(
                    hostname,
                    "unavailable",
                    status_code=status_code,
                    final_url=final_url,
                    evidence={"reason": "HTTP response was not 200"},
                )
            body = response.read(MAX_ROBOTS_BYTES + 1)
            if len(body) > MAX_ROBOTS_BYTES:
                raise ValueError("robots.txt exceeds the 1 MiB collection limit")
            if isinstance(body, str):
                content = body
                raw_body = body.encode("utf-8")
            else:
                raw_body = body
                content = body.decode("utf-8-sig", errors="replace")
            return _base_observation(
                hostname,
                "success",
                status_code=200,
                accessible=True,
                final_url=final_url,
                directives=parse_robots(content),
                evidence={
                    "content": content,
                    "content_sha256": hashlib.sha256(raw_body).hexdigest(),
                    "content_bytes": len(raw_body),
                },
                confidence="high",
            )
    except urllib.error.HTTPError as exc:
        return _base_observation(
            hostname,
            "unavailable",
            status_code=exc.code,
            evidence={"reason": "HTTP error response"},
            error=str(exc),
        )


def observe_host(hostname, cache_dir=DEFAULT_CACHE,
                 ttl_hours=DEFAULT_TTL_HOURS, timeout=DEFAULT_TIMEOUT,
                 opener=None, delay=DEFAULT_DELAY, sleeper=time.sleep,
                 last_request=None):
    hostname = normalize_hostname(hostname)
    cache_path = Path(cache_dir) / (cache_key(hostname) + ".json")
    cached = read_cache(cache_path, ttl_hours)
    # Successful and explicitly unavailable results are stable observations.
    # Errors are transient and must be retried rather than cached indefinitely.
    if isinstance(cached, dict) and cached.get("status") in ("success", "unavailable"):
        return cached

    if last_request is not None and last_request[0] is not None:
        elapsed = time.monotonic() - last_request[0]
        remaining = float(delay) - elapsed
        if remaining > 0:
            sleeper(remaining)

    observed_at = timestamp()
    try:
        result = fetch_robots(hostname, timeout=timeout, opener=opener)
        result["observed_at"] = observed_at
    except Exception as exc:
        result = _base_observation(
            hostname,
            "error",
            evidence={"error": type(exc).__name__, "message": str(exc)},
            confidence="low",
            error=str(exc),
        )
        result["observed_at"] = observed_at

    write_cache(cache_path, result)
    if last_request is not None:
        last_request[0] = time.monotonic()
    return result


def write_output(path, observations):
    observations = sorted(observations, key=lambda item: item["hostname"])
    document = {
        "observation_type": "robots",
        "created_at": timestamp(),
        "completed_count": len(observations),
        "observations": observations,
    }
    atomic_write_json(path, document)
    return document


def collect(hostnames, output=DEFAULT_OUTPUT, cache_dir=DEFAULT_CACHE,
            timeout=DEFAULT_TIMEOUT, delay=DEFAULT_DELAY, opener=None,
            sleeper=time.sleep):
    normalized = sorted({normalize_hostname(host) for host in hostnames})
    if len(normalized) > 20:
        raise ValueError("Robots audit is limited to the existing 20-host sample")

    output = Path(output)
    observations = {}
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
            previous_items = previous.get("observations", [])
            if isinstance(previous_items, list):
                for item in previous_items:
                    if (isinstance(item, dict)
                            and item.get("hostname") in normalized
                            and item.get("status") in ("success", "unavailable", "error")):
                        observations[item["hostname"]] = item
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            observations = {}

    last_request = [None]
    for hostname in normalized:
        current = observations.get(hostname)
        if current is not None and current.get("status") in ("success", "unavailable"):
            continue
        observations[hostname] = observe_host(
            hostname,
            cache_dir=cache_dir,
            timeout=timeout,
            opener=opener,
            delay=delay,
            sleeper=sleeper,
            last_request=last_request,
        )
        write_output(output, list(observations.values()))

    ordered = [observations[name] for name in sorted(observations)]
    write_output(output, ordered)
    return ordered


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Passively inventory robots.txt resources for the discovered TLS sample"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("collect")
    command.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    command.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    command.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    command.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    command.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)

    hostnames = load_sample(args.sample)
    observations = collect(
        hostnames,
        output=args.out,
        cache_dir=args.cache_dir,
        timeout=args.timeout,
        delay=args.delay,
    )
    failures = sum(item["status"] == "error" for item in observations)
    print(json.dumps({
        "requested_count": len(hostnames),
        "completed_count": len(observations),
        "error_count": failures,
        "output": str(args.out),
    }, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
