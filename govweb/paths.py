"""Resolve every on-disk location relative to the package, never the CWD.

Committed artifacts live under ``datasets/govweb``; anything regenerable
(response caches, per-host handshake state) lives under ``output/govweb``.
Both can be overridden for tests and for out-of-tree scouts.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent

DATASET_DIR = Path(
    os.environ.get("GOVWEB_DATASET_DIR", REPO_ROOT / "datasets" / "govweb")
).resolve()
OUTPUT_DIR = Path(
    os.environ.get("GOVWEB_OUTPUT_DIR", REPO_ROOT / "output" / "govweb")
).resolve()

OBSERVATION_DIR = DATASET_DIR / "observations"
SOURCE_DIR = DATASET_DIR / "sources"
CACHE_DIR = OUTPUT_DIR / "cache"

MANIFEST_DIR = PACKAGE_DIR / "manifests"
