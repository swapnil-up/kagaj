"""Dataset descriptors: validate `datasets/<id>/dataset.json` and build the index.

Contract: docs/dataset-manifest.md
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = REPO_ROOT / "datasets"
INDEX_PATH = DATASETS_DIR / "index.json"

SCHEMA_VERSION = "1.0"
DESCRIPTOR_NAME = "dataset.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
STATUS_VALUES = ("active", "experimental", "archived")
ARTIFACT_ROLES = ("primary", "canonical", "raw", "rollup", "reference", "metadata", "report", "chart")
FORMATS = ("csv", "csv.gz", "json", "txt", "md", "png", "sqlite", "db")
VERIFICATION_VALUES = ("verified", "partial", "none")
PRIMARY_ROLE = "primary"
# Formats that should be fingerprinted by the dataset's build file.
DATA_FORMATS = ("csv", "csv.gz", "json", "png", "sqlite", "db")

CSV_FORMATS = ("csv", "csv.gz")


@dataclass(frozen=True)
class Issue:
    dataset: str
    field: str
    message: str
    level: str = "error"

    def __str__(self) -> str:
        mark = "ERROR" if self.level == "error" else "warn "
        return f"{mark} {self.dataset}:{self.field}: {self.message}"


def discover() -> list[Path]:
    if not DATASETS_DIR.is_dir():
        return []
    return sorted(
        d for d in DATASETS_DIR.iterdir()
        if d.is_dir() and (d / DESCRIPTOR_NAME).exists() and not d.name.startswith("_")
    )


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _is_http(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _check_path(root: Path, value: Any, allow_dir: bool = False) -> tuple[Path | None, str | None]:
    """Resolve `value` under `root`. Returns (resolved, error)."""
    if not isinstance(value, str) or not value:
        return None, "must be a non-empty string"
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        return None, "must be a relative path without '..'"
    resolved = root / rel
    if allow_dir:
        if not resolved.is_dir():
            return None, f"directory not found: {_rel(resolved)}"
    elif not resolved.is_file():
        return None, f"file not found: {_rel(resolved)}"
    return resolved, None


def _matches(root: Path, pattern: str) -> list[Path]:
    """Files under `root` matching `pattern`; the descriptor never matches itself."""
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file() and p.name != DESCRIPTOR_NAME
    )


def fingerprint_paths(dataset_dir: Path, doc: dict[str, Any]) -> list[Path]:
    freshness = doc.get("freshness")
    if not isinstance(freshness, dict):
        return []
    value = freshness.get("fingerprint")
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [dataset_dir / str(name) for name in value if name]


def fingerprint_entries(dataset_dir: Path, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Artifacts declared by the fingerprint files, keyed by path."""
    entries: dict[str, dict[str, Any]] = {}
    for path in fingerprint_paths(dataset_dir, doc):
        if not path.is_file():
            continue
        try:
            data = load(path)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        raw = data.get("files") or data.get("artifacts") or {}
        if not isinstance(raw, dict):
            continue
        for key, value in raw.items():
            if isinstance(value, dict):
                entries.setdefault(str(key), value)
    return entries


def validate(dataset_dir: Path, check_hashes: bool = True) -> list[Issue]:
    name = dataset_dir.name
    issues: list[Issue] = []
    path = dataset_dir / DESCRIPTOR_NAME
    if not path.is_file():
        return [Issue(name, DESCRIPTOR_NAME, "descriptor missing")]

    try:
        doc = load(path)
    except (json.JSONDecodeError, OSError) as exc:
        return [Issue(name, DESCRIPTOR_NAME, f"unreadable: {exc}")]
    if not isinstance(doc, dict):
        return [Issue(name, DESCRIPTOR_NAME, "descriptor must be a JSON object")]

    def err(field: str, message: str) -> None:
        issues.append(Issue(name, field, message))

    def warn(field: str, message: str) -> None:
        issues.append(Issue(name, field, message, level="warning"))

    if doc.get("schema_version") != SCHEMA_VERSION:
        err("schema_version", f"expected {SCHEMA_VERSION!r}, got {doc.get('schema_version')!r}")

    dataset_id = doc.get("id")
    if not isinstance(dataset_id, str) or not ID_RE.match(dataset_id):
        err("id", "must match ^[a-z0-9][a-z0-9-]*$")
    elif dataset_id != name:
        err("id", f"{dataset_id!r} does not match directory {name!r}")

    for field in ("title", "description", "grain"):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            err(field, "required non-empty string")

    if doc.get("status") not in STATUS_VALUES:
        err("status", f"must be one of {', '.join(STATUS_VALUES)}")

    coverage = doc.get("coverage")
    if not isinstance(coverage, dict):
        err("coverage", "required object with start/end")
    else:
        for field in ("start", "end"):
            if not isinstance(coverage.get(field), str) or not coverage[field].strip():
                err(f"coverage.{field}", "required non-empty string")

    sources = doc.get("sources")
    if not isinstance(sources, list) or not sources:
        err("sources", "required non-empty list")
    else:
        seen: set[str] = set()
        for i, source in enumerate(sources):
            if not isinstance(source, dict):
                err(f"sources[{i}]", "must be an object")
                continue
            if not isinstance(source.get("name"), str) or not source["name"].strip():
                err(f"sources[{i}].name", "required non-empty string")
            url = source.get("url")
            if not _is_http(url) and url != "various":
                err(f"sources[{i}].url", "must be http(s):// or 'various'")
            elif _is_http(url):
                if url in seen:
                    err(f"sources[{i}].url", f"duplicate source {url}")
                seen.add(url)

    declared: list[str] = []
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        err("artifacts", "required non-empty list")
        artifacts = []
    prime = 0
    for i, artifact in enumerate(artifacts):
        field = f"artifacts[{i}]"
        if not isinstance(artifact, dict):
            err(field, "must be an object")
            continue
        pattern = artifact.get("pattern")
        if pattern is not None:
            if not isinstance(pattern, str) or not pattern:
                err(f"{field}.pattern", "must be a non-empty glob string")
                pattern = None
        resolved, problem = _check_path(dataset_dir, artifact.get("path"), allow_dir=pattern is not None)
        if problem:
            err(f"{field}.path", problem)
        elif pattern is None:
            declared.append(artifact["path"])
        else:
            matches = _matches(resolved, pattern)
            if not matches:
                err(f"{field}.pattern", f"no files match {pattern!r} in {_rel(resolved)}")
        if artifact.get("role") not in ARTIFACT_ROLES:
            err(f"{field}.role", f"must be one of {', '.join(ARTIFACT_ROLES)}")
        elif artifact["role"] == PRIMARY_ROLE:
            prime += 1
        if artifact.get("format") not in FORMATS:
            err(f"{field}.format", f"must be one of {', '.join(FORMATS)}")
        if resolved is not None and pattern is None and artifact.get("format") in CSV_FORMATS:
            if _csv_header(resolved) is None:
                err(f"{field}.path", "not a readable CSV")
    if artifacts and prime != 1:
        err("artifacts", f"expected exactly one {PRIMARY_ROLE} artifact, found {prime}")
    if len(declared) != len(set(declared)):
        err("artifacts", "duplicate artifact paths")

    for field in ("docs", "inventories"):
        values = doc.get(field, [])
        if not isinstance(values, list):
            err(field, "must be a list")
            continue
        for i, value in enumerate(values):
            _, problem = _check_path(dataset_dir if field == "docs" else REPO_ROOT, value)
            if problem:
                err(f"{field}[{i}]", problem)

    license_ = doc.get("license")
    if not isinstance(license_, dict):
        err("license", "required object with code/data")
    else:
        for field in ("code", "data"):
            if not isinstance(license_.get(field), str) or not license_[field].strip():
                err(f"license.{field}", "required non-empty string")

    verification = doc.get("verification")
    if not isinstance(verification, dict):
        err("verification", "required object")
    else:
        if verification.get("status") not in VERIFICATION_VALUES:
            err("verification.status", f"must be one of {', '.join(VERIFICATION_VALUES)}")
        if not isinstance(verification.get("method"), str) or not verification["method"].strip():
            err("verification.method", "required non-empty string")
        report = verification.get("report")
        if report:
            _, problem = _check_path(dataset_dir, report)
            if problem:
                err("verification.report", problem)

    pipeline = doc.get("pipeline")
    if pipeline is not None:
        if not isinstance(pipeline, dict):
            err("pipeline", "must be an object")
        else:
            cli = pipeline.get("cli")
            if cli is not None and not (
                isinstance(cli, str) or
                (isinstance(cli, list) and all(isinstance(c, str) for c in cli))
            ):
                err("pipeline.cli", "must be a string or a list of strings")
            plan = pipeline.get("plan")
            if plan:
                _, problem = _check_path(REPO_ROOT, plan)
                if problem:
                    err("pipeline.plan", problem)

    for field in ("tags", "notes"):
        values = doc.get(field, [])
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            err(field, "must be a list of strings")

    fp_files = fingerprint_paths(dataset_dir, doc)
    if not fp_files:
        warn("freshness", "no fingerprint file; freshness unknown")
    for fp_file in fp_files:
        if not fp_file.is_file():
            err("freshness.fingerprint", f"file not found: {_rel(fp_file)}")

    entries = fingerprint_entries(dataset_dir, doc)
    if entries:
        missing = sorted(set(entries) - set(declared))
        if missing:
            err("artifacts", f"fingerprint declares undeclared artifacts: {', '.join(missing)}")
        doc_paths = set(doc.get("docs")) if isinstance(doc.get("docs"), list) else set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("pattern"):
                continue
            path_ = artifact.get("path")
            if path_ in entries or path_ in doc_paths or artifact.get("format") not in DATA_FORMATS:
                continue
            warn("artifacts", f"{path_} is not covered by the fingerprint file")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("path") not in entries:
                continue
            info = entries[artifact["path"]]
            resolved = dataset_dir / artifact["path"]
            if not resolved.is_file():
                continue
            if check_hashes:
                digest, size = _sha256(resolved)
                expected = info.get("sha256")
                if expected and expected != digest:
                    err(artifact["path"], "sha256 disagrees with fingerprint file (stale build)")
                expected_bytes = info.get("bytes")
                if expected_bytes is not None and expected_bytes != size:
                    err(artifact["path"], "byte size disagrees with fingerprint file (stale build)")
            elif "bytes" in info and info["bytes"] != resolved.stat().st_size:
                err(artifact["path"], "byte size disagrees with fingerprint file (stale build)")

    return issues


def _csv_header(path: Path) -> list[str] | None:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8", newline="") as handle:  # type: ignore[operator]
            row = next(csv.reader(handle), None)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return list(row) if row else None


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _artifact_entry(dataset_dir: Path, artifact: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    pattern = artifact.get("pattern")
    resolved = dataset_dir / artifact["path"]
    entry: dict[str, Any] = {
        "path": artifact["path"],
        "role": artifact.get("role"),
        "format": artifact.get("format"),
    }
    if pattern:
        matches = _matches(resolved, str(pattern))
        entry["pattern"] = pattern
        entry["file_count"] = len(matches)
        entry["bytes"] = sum(p.stat().st_size for p in matches)
    else:
        entry["bytes"] = resolved.stat().st_size
        if artifact.get("format") in CSV_FORMATS:
            header = _csv_header(resolved)
            if header:
                entry["columns"] = header
    for key in ("rows", "sha256"):
        if key in info:
            entry[key] = info[key]
    if "description" in artifact:
        entry["description"] = artifact["description"]
    return entry


def build_index() -> dict[str, Any]:
    datasets: list[dict[str, Any]] = []
    for dataset_dir in discover():
        doc = load(dataset_dir / DESCRIPTOR_NAME)
        entries = fingerprint_entries(dataset_dir, doc)
        entry = {
            key: doc[key]
            for key in (
                "id", "title", "status", "description", "grain",
                "coverage", "sources", "verification", "pipeline", "license",
            )
            if key in doc
        }
        for key in ("tags", "notes", "docs", "inventories"):
            if key in doc:
                entry[key] = doc[key]
        freshness: dict[str, Any] = {}
        for fp_file in fingerprint_paths(dataset_dir, doc):
            if not fp_file.is_file():
                continue
            data = load(fp_file)
            if not isinstance(data, dict):
                continue
            if "fingerprints" not in freshness:
                freshness["fingerprints"] = []
            freshness["fingerprints"].append(fp_file.name)
            for key in ("generated_at", "commit"):
                if key in data and key not in freshness:
                    freshness[key] = data[key]
            if isinstance(data.get("git"), dict) and "commit" in data["git"]:
                freshness.setdefault("commit", data["git"]["commit"])
            elif "git_revision" in data:
                freshness.setdefault("commit", data["git_revision"])
        entry["freshness"] = freshness
        entry["artifacts"] = [
            _artifact_entry(dataset_dir, artifact, entries.get(artifact["path"], {}))
            for artifact in doc.get("artifacts", [])
            if isinstance(artifact, dict) and (dataset_dir / artifact["path"]).exists()
        ]
        datasets.append(entry)
    return {"schema_version": SCHEMA_VERSION, "datasets": datasets}


def write_index(path: Path = INDEX_PATH) -> dict[str, Any]:
    index = build_index()
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return index


def validate_all(check_hashes: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    for dataset_dir in discover():
        issues.extend(validate(dataset_dir, check_hashes=check_hashes))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kagaj_core.manifest", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate_cmd = sub.add_parser("validate", help="validate every dataset descriptor")
    validate_cmd.add_argument("--quick", action="store_true", help="skip SHA-256 recomputation")

    sub.add_parser("index", help="regenerate datasets/index.json")
    sub.add_parser("check", help="validate and fail if datasets/index.json is stale")

    args = parser.parse_args(argv)

    if args.command in {"validate", "check"}:
        issues = validate_all(check_hashes=not getattr(args, "quick", False))
        for issue in issues:
            print(issue, file=sys.stderr if issue.level == "error" else sys.stdout)
        errors = [i for i in issues if i.level == "error"]
        print(f"{len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
        if errors:
            return 1
        if args.command == "check":
            committed = INDEX_PATH.read_text(encoding="utf-8") if INDEX_PATH.is_file() else ""
            expected = json.dumps(build_index(), ensure_ascii=False, indent=2) + "\n"
            if committed != expected:
                print("datasets/index.json is stale — run: python -m kagaj_core.manifest index", file=sys.stderr)
                return 1
        return 0

    index = write_index()
    print(f"wrote {_rel(INDEX_PATH)} ({len(index['datasets'])} datasets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
