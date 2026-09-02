"""Download a Click revision and run the benchmark against its real hooks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent
DEFAULT_LOCK = ROOT / "target.lock.json"
GITHUB_REPOSITORY = re.compile(
    r"(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
)


def _official_target() -> dict[str, str]:
    try:
        value: Any = json.loads(DEFAULT_LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"could not read {DEFAULT_LOCK.name}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{DEFAULT_LOCK.name} must contain an object")
    repository = value.get("repository")
    commit = value.get("commit")
    if not isinstance(repository, str) or not isinstance(commit, str):
        raise RuntimeError(f"{DEFAULT_LOCK.name} is missing repository or commit")
    return {"repository": repository, "commit": commit}


def normalize_repository(value: str) -> str:
    match = GITHUB_REPOSITORY.fullmatch(value.strip())
    if match is None:
        raise ValueError("target repository must be OWNER/REPO or a GitHub HTTPS URL")
    owner, repository = match.groups()
    if owner in {".", ".."} or repository in {".", ".."}:
        raise ValueError("target repository must use ordinary GitHub path segments")
    return f"https://github.com/{owner}/{repository}.git"


def validate_ref(value: str) -> str:
    candidate = value.strip()
    if (
        not candidate
        or len(candidate) > 200
        or candidate.startswith("-")
        or any(character.isspace() or ord(character) < 32 for character in candidate)
    ):
        raise ValueError("target ref must be a non-empty branch, tag, or commit")
    return candidate


def _run(argv: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(argv, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}: {argv[0]}")


def _capture(argv: list[str], *, cwd: Path) -> str:
    result = subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed with exit code {result.returncode}: {argv[0]}")
    return result.stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    official = _official_target()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-repository",
        default=os.environ.get("CLICK_BENCH_TARGET_REPOSITORY", official["repository"]),
        help="public GitHub repository as OWNER/REPO or an HTTPS URL",
    )
    parser.add_argument(
        "--target-ref",
        default=os.environ.get("CLICK_BENCH_TARGET_REF", official["commit"]),
        help="branch, tag, or full commit to evaluate",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="run benchmark regression tests instead of the full matrix",
    )
    parser.add_argument(
        "--suite",
        choices=(
            "evidence-reuse-500",
            "dependency-omission-100",
            "unnecessary-rerun-100",
        ),
        default="evidence-reuse-500",
        help="benchmark suite to run",
    )
    arguments, benchmark_args = parser.parse_known_args(argv)
    if benchmark_args[:1] == ["--"]:
        benchmark_args = benchmark_args[1:]
    repository = normalize_repository(arguments.target_repository)
    target_ref = validate_ref(arguments.target_ref)

    with tempfile.TemporaryDirectory(prefix="click-benchmark-target-") as temporary:
        temporary_root = Path(temporary)
        target = temporary_root / "click"
        print(f"Downloading Click target {repository} at {target_ref}...", flush=True)
        _run(
            [
                "git",
                "clone",
                "--quiet",
                "--filter=blob:none",
                "--no-checkout",
                "--depth",
                "1",
                repository,
                str(target),
            ]
        )
        _run(["git", "fetch", "--quiet", "--depth", "1", "origin", target_ref], cwd=target)
        _run(["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=target)
        revision = _capture(["git", "rev-parse", "HEAD"], cwd=target)
        print(f"Evaluating resolved Click commit {revision}", flush=True)
        runtime_lock = temporary_root / "target.lock.json"
        runtime_lock.write_text(
            json.dumps(
                {"repository": repository.removesuffix(".git"), "commit": revision},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment["CLICK_REPO"] = str(target)
        environment["CLICK_TARGET_LOCK"] = str(runtime_lock)
        if arguments.tests:
            command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
        else:
            modules = {
                "evidence-reuse-500": "benchmarks.evidence_reuse",
                "dependency-omission-100": "benchmarks.dependency_omission",
                "unnecessary-rerun-100": "benchmarks.unnecessary_rerun",
            }
            module = modules[arguments.suite]
            command = [sys.executable, "-m", module, *benchmark_args]
        completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
