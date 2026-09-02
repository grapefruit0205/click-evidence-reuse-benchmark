"""Load the exact Click revision selected by the benchmark repository."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = BENCHMARK_ROOT / "target.lock.json"
DEFAULT_CLICK_ROOT = BENCHMARK_ROOT / "target" / "click"
REQUIRED_HOOKS = (
    "click_dependency_cache.py",
    "click_evidence.py",
    "click_host_coverage.py",
    "click_verification.py",
)


def _lock_path() -> Path:
    configured = os.environ.get("CLICK_TARGET_LOCK", "").strip()
    return Path(configured).expanduser().resolve() if configured else LOCK_PATH


def _load_lock() -> dict[str, str]:
    lock_path = _lock_path()
    try:
        value: Any = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"could not read target lock {lock_path}: {error}") from error
    if not isinstance(value, dict) or set(value) != {"repository", "commit"}:
        raise RuntimeError("target.lock.json must contain repository and commit")
    repository = value.get("repository")
    commit = value.get("commit")
    if not isinstance(repository, str) or not repository.startswith("https://github.com/"):
        raise RuntimeError("target.lock.json repository must be a GitHub HTTPS URL")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("target.lock.json commit must be a full Git SHA")
    return {"repository": repository, "commit": commit}


def configure_click_target() -> tuple[Path, dict[str, str]]:
    """Validate and import the pinned Click checkout without network access."""
    lock = _load_lock()
    configured = os.environ.get("CLICK_REPO", "").strip()
    root = Path(configured).expanduser() if configured else DEFAULT_CLICK_ROOT
    root = root.resolve()
    missing = [name for name in REQUIRED_HOOKS if not (root / "hooks" / name).is_file()]
    if missing:
        raise RuntimeError(
            "Click target checkout is missing required hooks at "
            f"{root}; clone the locked revision into target/click"
        )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    revision = result.stdout.strip()
    if result.returncode != 0 or revision != lock["commit"]:
        raise RuntimeError(
            "Click target revision does not match target.lock.json: "
            f"expected {lock['commit']}, found {revision or 'unknown'}"
        )
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root, lock
