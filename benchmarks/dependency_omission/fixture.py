"""Materialize language fixtures from generated cases.

This module knows fixture behavior, but imports neither Click nor its manifest
matcher. The runner chooses the omitted path only after parsing a real baseline
process run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from .cases import OmissionCase


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


@dataclass(frozen=True)
class FixturePlan:
    source_path: str
    mutable_paths: tuple[str, ...]
    expected_value: str


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def materialize(case: OmissionCase, root: Path) -> FixturePlan:
    """Create one repository whose baseline behavior is known to pass."""
    source_names = {
        "python": "omission_check.py",
        "node": "omission_check.js",
        "c": "omission_check.c",
        "java": "OmissionCheck.java",
    }
    source_name = source_names[case.language]
    shutil.copy2(FIXTURE_ROOT / source_name, root / source_name)
    _write(root / ".gitignore", "build/\n")
    _write(root / "stable.txt", "stable-control")

    expected = f"baseline-{case.token}"
    values = {"mode": case.mode, "expected": expected}
    mutable_paths: tuple[str, ...]

    if case.mode == "direct-file":
        target = f"runtime/direct/{case.token}.txt"
        _write(root / target, expected)
        values["target"] = target
        mutable_paths = (target,)
    elif case.mode == "nested-pointer":
        pointer = f"runtime/pointers/{case.token}.txt"
        target = f"runtime/nested/{case.token}.txt"
        _write(root / pointer, target)
        _write(root / target, expected)
        values["pointer"] = pointer
        mutable_paths = (pointer, target)
    elif case.mode == "directory-membership":
        target = f"runtime/listing/{case.token}/"
        _write(root / target / "expected.txt", expected)
        values["target"] = target
        mutable_paths = (target,)
    elif case.mode == "missing-file":
        target = f"runtime/optional/{case.token}.txt"
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        values["target"] = target
        mutable_paths = (target,)
    elif case.mode == "child-process":
        target = f"runtime/child/{case.token}.txt"
        _write(root / target, expected)
        values["target"] = target
        mutable_paths = (target,)
    else:
        raise ValueError(f"unknown fixture mode: {case.mode}")

    spec = "".join(f"{key}={value}\n" for key, value in values.items())
    _write(root / "case.spec", spec)
    return FixturePlan(source_name, mutable_paths, expected)


def mutate_omitted_dependency(
    case: OmissionCase,
    plan: FixturePlan,
    root: Path,
    omitted_path: str,
) -> str:
    """Change only the observed path that the manifest deliberately omitted."""
    if omitted_path not in plan.mutable_paths:
        raise ValueError(f"not a mutable runtime dependency: {omitted_path}")
    target = root / omitted_path.rstrip("/")

    if case.mode == "directory-membership":
        if case.variant % 2:
            (target / "expected.txt").unlink()
            return "delete-directory-member"
        _write(target / f"unexpected-{case.variant}.txt", "unexpected")
        return "add-directory-member"
    if case.mode == "missing-file":
        _write(target, "unexpectedly-present")
        return "create-missing-file"
    if case.mode == "nested-pointer" and "/pointers/" in omitted_path:
        replacement = f"runtime/missing/{case.token}.txt"
        _write(target, replacement)
        return "redirect-pointer"
    if case.variant % 2:
        target.unlink()
        return "delete-file"
    _write(target, f"mutated-{case.token}")
    return "overwrite-file"
