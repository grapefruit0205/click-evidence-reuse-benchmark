"""Build safe changes independently from Click's reuse implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from benchmarks.dependency_omission.fixture import FixturePlan, materialize

from .cases import SafeChangeCase


@dataclass(frozen=True)
class SafeFixturePlan:
    runtime: FixturePlan
    changed_path: str


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _source_suffix(language: str) -> str:
    return {"python": ".py", "node": ".js", "c": ".c", "java": ".java"}[
        language
    ]


def materialize_safe_change(case: SafeChangeCase, root: Path) -> SafeFixturePlan:
    runtime = materialize(case, root)
    suffix = _source_suffix(case.language)
    paths = {
        "documentation": f"docs/guide-{case.token}.md",
        "unused-example": f"examples/unused-{case.token}{suffix}",
        "unread-asset": f"assets/banner-{case.token}.txt",
        "tooling-note": f"tools/notes-{case.token}.txt",
        "unrelated-source": f"unrelated/unused-{case.token}{suffix}",
    }
    changed_path = paths[case.change_kind]
    _write(root / changed_path, f"baseline-unobserved-{case.token}")
    return SafeFixturePlan(runtime, changed_path)


def manifest_patterns(case: SafeChangeCase, plan: SafeFixturePlan) -> tuple[str, ...]:
    source = plan.runtime.source_path
    suffix = _source_suffix(case.language)
    styles = {
        "exact-controls": (source, "case.spec", "stable.txt"),
        "runtime-envelope": (source, "case.spec", "stable.txt", "runtime/**"),
        "repository-wide": ("**",),
        "mixed-envelopes": (
            source,
            "case.spec",
            "stable.txt",
            "runtime/**",
            "docs/**",
            "examples/**",
            "assets/**",
            "tools/**",
            "unrelated/**",
        ),
        "language-envelope": (source, "case.spec", "stable.txt", f"**/*{suffix}"),
    }
    return tuple(sorted(styles[case.manifest_style]))


def mutate_safe_path(case: SafeChangeCase, root: Path, path: str) -> str:
    target = root / path
    if case.variant == 2:
        target.unlink()
        return "delete-unobserved-file"
    if case.variant in {1, 4}:
        _write(target, f"replacement-unobserved-{case.token}")
        return "replace-unobserved-file"
    target.write_text(
        target.read_text(encoding="utf-8") + f"\nappend-{case.token}",
        encoding="utf-8",
    )
    return "append-unobserved-file"
