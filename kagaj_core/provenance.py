"""Hashes, git state, and reproducible build manifests.

Every shipped artifact should be checkable from its manifest. This module keeps
the format small and deterministic: a git summary, a timestamp supplied by the
caller, and ``bytes``/``sha256`` for each named file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA_VERSION = 1
_CHUNK = 1 << 16


def sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file, reading it in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(repo_root: str | Path | None = None) -> dict:
    """Return ``commit``, ``describe``, ``dirty``, and ``clean`` for a repo."""
    root = Path(repo_root or Path.cwd())

    def run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True,
                check=True)
            return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            return ""

    porcelain = run("status", "--porcelain")
    dirty = bool(porcelain)
    return {
        "commit": run("rev-parse", "HEAD"),
        "describe": run("describe", "--tags", "--always", "--dirty"),
        "dirty": dirty,
        "clean": not dirty,
    }


def artifact_manifest(paths: Iterable[str | Path] | Mapping[str, str | Path],
                      root: str | Path | None = None) -> dict:
    """Return ``{name: {bytes, sha256}}`` for files under *root*."""
    base = Path(root or Path.cwd())
    items = paths.items() if isinstance(paths, Mapping) else (
        (None, path) for path in paths)
    files: dict[str, dict] = {}
    for name, path in items:
        file_path = Path(path)
        if not file_path.is_absolute() and base is not None:
            file_path = base / file_path
        if name is None:
            try:
                name = file_path.resolve().relative_to(base.resolve()).as_posix()
            except ValueError:
                name = file_path.name
        files[str(name)] = {
            "bytes": file_path.stat().st_size,
            "sha256": sha256_file(file_path),
        }
    return files


def build_manifest(paths: Iterable[str | Path] | Mapping[str, str | Path],
                   repo_root: str | Path | None = None, *,
                   extra: Mapping[str, object] | None = None,
                   generated_at: str | None = None,
                   schema_version: int = SCHEMA_VERSION) -> dict:
    """Build a manifest suitable for writing next to shipped artifacts."""
    base = Path(repo_root or Path.cwd())
    manifest = {
        "schema_version": schema_version,
        "generated_at": generated_at or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": git_state(base),
        "files": artifact_manifest(paths, base),
    }
    if extra:
        manifest.update(extra)
    return manifest


def verify_manifest(manifest: Mapping, root: str | Path | None = None) -> list[str]:
    """Return a list of human-readable mismatches; an empty list means OK."""
    base = Path(root or Path.cwd())
    problems: list[str] = []
    files = manifest.get("files") or {}
    if not files:
        problems.append("manifest has no files")
    for name, expected in files.items():
        path = base / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue
        actual_bytes = path.stat().st_size
        if expected.get("bytes") is not None and actual_bytes != expected["bytes"]:
            problems.append(
                f"{name}: bytes {actual_bytes} != {expected['bytes']}")
        actual_sha = sha256_file(path)
        if expected.get("sha256") and actual_sha != expected["sha256"]:
            problems.append(f"{name}: sha256 {actual_sha} != {expected['sha256']}")
    return problems


def require_clean(manifest: Mapping) -> list[str]:
    """Return a problem when the manifest records a dirty git tree."""
    git = manifest.get("git") or {}
    if git.get("dirty"):
        return ["git tree was dirty when the manifest was written"]
    if not git.get("commit"):
        return ["manifest has no git commit"]
    return []


def write_manifest(path: str | Path, manifest: Mapping) -> Path:
    """Write *manifest* as stable, UTF-8 JSON."""
    destination = Path(path)
    destination.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return destination
