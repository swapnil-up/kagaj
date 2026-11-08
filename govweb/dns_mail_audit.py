import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from . import paths

USER_AGENT = "govweb-passive-audit/1.0 (Kagaj public-infrastructure research)"
DEFAULT_SAMPLE = paths.DATASET_DIR / "tls_sample.json"
DEFAULT_OUTPUT = paths.OBSERVATION_DIR / "dns_mail_observations.json"
DEFAULT_CACHE = paths.CACHE_DIR / "dns_mail"
DEFAULT_TIMEOUT = 15
DEFAULT_DELAY = 1.0
DEFAULT_TTL_HOURS = 168
DOH_ENDPOINT = "https://cloudflare-dns.com/dns-query"
RECORD_TYPES = ("A", "AAAA", "MX", "NS", "TXT", "CAA")
TYPE_CODES = {"A": 1, "NS": 2, "CNAME": 5, "SOA": 6, "MX": 15, "TXT": 16, "AAAA": 28, "CAA": 257}


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value=None):
    return (value or utc_now()).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_hostname(value):
    value = str(value).strip().lower().rstrip(".")
    if not value or "/" in value or ":" in value or "*" in value:
        raise ValueError("Invalid hostname")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid IDNA hostname") from exc
    if not value.endswith(".gov.np"):
        raise ValueError("Only discovered .gov.np hostnames are accepted")
    labels = value.split(".")
    if any(not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels):
        raise ValueError("Invalid DNS hostname")
    return value


def load_sample(path=DEFAULT_SAMPLE):
    with Path(path).open(encoding="utf-8") as handle:
        document = json.load(handle)
    values = document.get("hostnames")
    if not isinstance(values, list):
        raise ValueError("TLS sample must contain a hostnames list")
    result = sorted({normalize_hostname(item) for item in values})
    if len(result) > 20:
        raise ValueError("DNS/mail audit is limited to the existing 20-host sample")
    return result


def cache_key(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_cache(path, ttl_hours=DEFAULT_TTL_HOURS):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(payload["cached_at"].replace("Z", "+00:00"))
        if utc_now() - observed > timedelta(hours=ttl_hours):
            return None
        return payload.get("value")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def write_cache(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"cached_at": timestamp(), "value": value}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def query_dns(name, record_type, timeout=DEFAULT_TIMEOUT, opener=None):
    if record_type not in TYPE_CODES:
        raise ValueError("Unsupported DNS record type")
    if not name or any(ch.isspace() for ch in name):
        raise ValueError("Invalid DNS query name")
    params = urllib.parse.urlencode({"name": name, "type": record_type})
    url = DOH_ENDPOINT + "?" + params
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/dns-json"})
    open_request = opener or urllib.request.urlopen
    with open_request(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("Status") not in (0, 3):
        raise ValueError("DNS-over-HTTPS returned an invalid response")
    answers = payload.get("Answer") or []
    records = []
    for answer in answers:
        if answer.get("type") == TYPE_CODES[record_type]:
            records.append(str(answer.get("data", "")))
    return sorted(set(records)), {"status": payload.get("Status"), "resolver": "Cloudflare DNS-over-HTTPS", "query_name": name, "query_type": record_type, "source_url": url, "observed_at": timestamp()}


def evaluate_spf(txt_records):
    candidates = [record.strip().strip('"') for record in txt_records if record.strip().lower().startswith("v=spf1")]
    if not candidates:
        return {"status": "missing", "record": None, "all_qualifier": None, "assessment": "no SPF record was found", "confidence": "high", "evidence": ["No TXT record beginning with v=spf1 was returned"]}
    if len(candidates) > 1:
        return {"status": "multiple_records", "record": candidates, "all_qualifier": None, "assessment": "multiple SPF records can cause SPF permerror", "confidence": "high", "evidence": ["More than one SPF TXT record was returned"]}
    record = candidates[0]
    tokens = record.split()
    if not tokens or tokens[0].lower() != "v=spf1":
        return {"status": "invalid", "record": record, "all_qualifier": None, "assessment": "malformed SPF version marker", "confidence": "medium", "evidence": ["SPF record did not begin with v=spf1"]}
    all_tokens = [token for token in tokens[1:] if re.fullmatch(r"[+?~-]?all", token, flags=re.IGNORECASE)]
    if len(all_tokens) != 1:
        status, assessment, qualifier = "missing_all", "SPF record does not contain exactly one all mechanism", None
    else:
        token = all_tokens[0]
        qualifier = token[:-3] or "+"
        if qualifier == "-":
            status, assessment = "enforced", "SPF ends with -all (hard fail for unmatched senders)"
        elif qualifier == "~":
            status, assessment = "softfail", "SPF ends with ~all (soft fail for unmatched senders)"
        elif qualifier == "?":
            status, assessment = "neutral", "SPF ends with ?all (neutral for unmatched senders)"
        else:
            status, assessment = "permissive", "SPF ends with +all (permits all senders)"
    return {"status": status, "record": record, "all_qualifier": qualifier, "assessment": assessment, "confidence": "high", "evidence": ["Evaluated the published SPF TXT record and its all mechanism; included mechanisms were not recursively evaluated"]}


def evaluate_dmarc(txt_records):
    candidates = [record.strip().strip('"') for record in txt_records if record.strip().lower().startswith("v=dmarc1")]
    if not candidates:
        return {"status": "missing", "record": None, "policy": None, "subdomain_policy": None, "tags": {}, "assessment": "no DMARC record was found", "confidence": "high", "evidence": ["No DMARC TXT record was returned at the _dmarc name"]}
    if len(candidates) > 1:
        return {"status": "multiple_records", "record": candidates, "policy": None, "subdomain_policy": None, "tags": {}, "assessment": "multiple DMARC records require correction", "confidence": "high", "evidence": ["More than one DMARC TXT record was returned"]}
    record = candidates[0]
    tags = {}
    for part in record.split(";")[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        if key:
            tags[key] = value.strip()
    policy = tags.get("p", "").lower()
    subdomain_policy = tags.get("sp", "").lower() or None
    if tags.get("v", "").upper() not in ("", "DMARC1") or policy not in ("none", "quarantine", "reject"):
        status, assessment = "invalid", "DMARC record has an invalid or missing policy tag"
    elif policy == "none":
        status, assessment = "monitoring", "DMARC policy is p=none and does not request quarantine or rejection"
    elif policy == "quarantine":
        status, assessment = "quarantine", "DMARC requests quarantine for failing mail"
    else:
        status, assessment = "reject", "DMARC requests rejection for failing mail"
    return {"status": status, "record": record, "policy": policy or None, "subdomain_policy": subdomain_policy, "tags": tags, "assessment": assessment, "confidence": "high", "evidence": ["Parsed the published DMARC TXT record; policy percentage and receiver-specific enforcement are not independently verified"]}


def collect_record_set(hostname, cache_dir, timeout=DEFAULT_TIMEOUT, queryer=query_dns, delay=DEFAULT_DELAY):
    records = {}
    evidence = []
    errors = []
    for record_type in RECORD_TYPES:
        cache_path = Path(cache_dir) / (cache_key(hostname + "|" + record_type) + ".json")
        cached = read_cache(cache_path)
        if cached is not None:
            records[record_type] = cached["records"]
            evidence.append(cached["evidence"])
            continue
        try:
            values, query_evidence = queryer(hostname, record_type, timeout=timeout)
            item = {"records": values, "evidence": query_evidence}
            write_cache(cache_path, item)
            records[record_type] = values
            evidence.append(query_evidence)
        except Exception as exc:
            records[record_type] = []
            errors.append({"record_type": record_type, "error": type(exc).__name__ + ": " + str(exc)})
        if delay > 0:
            time.sleep(delay)
    dmarc_name = "_dmarc." + hostname
    dmarc_cache = Path(cache_dir) / (cache_key(dmarc_name + "|TXT") + ".json")
    cached = read_cache(dmarc_cache)
    if cached is not None:
        dmarc_txt = cached["records"]
        evidence.append(cached["evidence"])
    else:
        try:
            dmarc_txt, query_evidence = queryer(dmarc_name, "TXT", timeout=timeout)
            write_cache(dmarc_cache, {"records": dmarc_txt, "evidence": query_evidence})
            evidence.append(query_evidence)
        except Exception as exc:
            dmarc_txt = []
            errors.append({"record_type": "DMARC_TXT", "error": type(exc).__name__ + ": " + str(exc)})
        if delay > 0:
            time.sleep(delay)
    return records, dmarc_txt, evidence, errors


def observe_host(hostname, cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT, queryer=query_dns, delay=DEFAULT_DELAY):
    hostname = normalize_hostname(hostname)
    cache_path = Path(cache_dir) / (cache_key(hostname + "|observation") + ".json")
    cached = read_cache(cache_path)
    if cached is not None:
        return cached
    records, dmarc_txt, evidence, errors = collect_record_set(hostname, cache_dir, timeout, queryer, delay)
    spf = evaluate_spf(records.get("TXT", []))
    dmarc = evaluate_dmarc(dmarc_txt)
    observation = {
        "municipality_id": None,
        "site_hostname": hostname,
        "observation_type": "dns_mail_security",
        "observed_at": timestamp(),
        "source_url": DOH_ENDPOINT,
        "status": "partial" if errors else "ok",
        "dns_records": records,
        "dmarc_txt_records": dmarc_txt,
        "mail_security": {"mx_present": bool(records.get("MX")), "spf": spf, "dmarc": dmarc},
        "evidence": evidence,
        "errors": errors,
        "confidence": "medium" if errors else "high"
    }
    write_cache(cache_path, observation)
    return observation


def collect(sample_path=DEFAULT_SAMPLE, output_path=DEFAULT_OUTPUT, cache_dir=DEFAULT_CACHE, timeout=DEFAULT_TIMEOUT, delay=DEFAULT_DELAY):
    hostnames = load_sample(sample_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    for hostname in hostnames:
        observations.append(observe_host(hostname, cache_dir, timeout, delay=delay))
        document = {"observation_type": "dns_mail_security", "created_at": timestamp(), "requested_hostname_count": len(hostnames), "completed_count": len(observations), "observations": observations}
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(output_path)
    if not hostnames:
        output_path.write_text(json.dumps({"observation_type": "dns_mail_security", "created_at": timestamp(), "requested_hostname_count": 0, "completed_count": 0, "observations": []}, indent=2) + "\n", encoding="utf-8")
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Passive DNS and mail-security audit for discovered .gov.np sites")
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("collect")
    command.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    command.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    command.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    command.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    command.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args(argv)
    if args.command == "collect":
        print(collect(args.sample, args.out, args.cache, args.timeout, args.delay))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
