"""Run 100 black-box safe changes and count unnecessary reruns."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Sequence

from benchmarks.dependency_omission.observer import (
    OBSERVATION_SOURCE,
    parse_observation,
)
from benchmarks.dependency_omission.runner import (
    CLICK_TARGET,
    CONTRACT_DIGEST,
    DECISION_ENGINE,
    HOST_COVERAGE,
    ExecutionResult,
    RuntimeTools,
    _checks,
    _observed_receipt,
    _resolve_tools,
    _run_checks,
    _run_git,
    _source,
    _start_java_container,
    _stop_java_container,
    _write_manifest,
)
from hooks import click_dependency_cache, click_verification

from .cases import DEFAULT_SEED, LANGUAGES, SafeChangeCase, generate_cases
from .fixture import (
    manifest_patterns,
    materialize_safe_change,
    mutate_safe_path,
)


@dataclass(frozen=True)
class SafeChangeResult:
    case_id: str
    language: str
    runtime_mode: str
    change_kind: str
    changed_path: str
    mutation: str
    manifest_style: str
    manifest_patterns: tuple[str, ...]
    observed_paths: tuple[str, ...]
    observed_child_processes: int
    baseline_passed: bool
    observation_complete: bool
    changed_path_unobserved: bool
    current_receipt_available: bool
    oracle_reuse_safe: bool
    oracle_expected_rerun_pass: bool
    decision_reuse: bool
    actual_rerun: ExecutionResult

    @property
    def correct_reuse(self) -> bool:
        return self.oracle_reuse_safe and self.decision_reuse

    @property
    def correct_invalidation(self) -> bool:
        return not self.oracle_reuse_safe and not self.decision_reuse

    @property
    def unsafe_reuse(self) -> bool:
        return not self.oracle_reuse_safe and self.decision_reuse

    @property
    def over_conservative_rerun(self) -> bool:
        return self.oracle_reuse_safe and not self.decision_reuse

    @property
    def actual_rerun_matches_oracle(self) -> bool:
        return self.actual_rerun.passed == self.oracle_expected_rerun_pass


def _metrics(cases: Iterable[SafeChangeResult]) -> dict[str, Any]:
    selected = tuple(cases)
    total = len(selected)
    correct_reuse = sum(case.correct_reuse for case in selected)
    correct_invalidation = sum(case.correct_invalidation for case in selected)
    correct = correct_reuse + correct_invalidation
    return {
        "total_cases": total,
        "decision_correct": correct,
        "decision_accuracy_percent": round(100.0 * correct / total, 1) if total else 0.0,
        "correct_reuse": correct_reuse,
        "correct_invalidation": correct_invalidation,
        "unsafe_reuse": sum(case.unsafe_reuse for case in selected),
        "over_conservative_rerun": sum(case.over_conservative_rerun for case in selected),
        "safe_reuse_capture_percent": (
            round(100.0 * correct_reuse / total, 1) if total else 0.0
        ),
        "actual_rerun_pass": sum(case.actual_rerun.passed for case in selected),
        "actual_rerun_fail": sum(not case.actual_rerun.passed for case in selected),
        "actual_rerun_oracle_mismatch": sum(
            not case.actual_rerun_matches_oracle for case in selected
        ),
        "complete_observations": sum(case.observation_complete for case in selected),
        "changed_paths_unobserved": sum(case.changed_path_unobserved for case in selected),
        "current_receipts_available": sum(
            case.current_receipt_available for case in selected
        ),
    }


@dataclass(frozen=True)
class UnnecessaryRerunReport:
    seed: int
    cases: tuple[SafeChangeResult, ...]
    toolchains: tuple[tuple[str, str], ...]

    @property
    def summary(self) -> dict[str, Any]:
        return _metrics(self.cases)

    @property
    def over_conservative_rerun(self) -> int:
        return int(self.summary["over_conservative_rerun"])

    @property
    def oracle_mismatch(self) -> int:
        return int(self.summary["actual_rerun_oracle_mismatch"])

    def _by(self, attribute: str) -> dict[str, dict[str, Any]]:
        return {
            name: _metrics(
                case for case in self.cases if str(getattr(case, attribute)) == name
            )
            for name in sorted({str(getattr(case, attribute)) for case in self.cases})
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary,
            "suite": "unnecessary-rerun-100",
            "seed": self.seed,
            "decision_engine": DECISION_ENGINE,
            "click_target": CLICK_TARGET,
            "observation_source": OBSERVATION_SOURCE,
            "oracle_source": "unobserved tracked-file mutation plus actual passing rerun",
            "toolchains": dict(self.toolchains),
            "by_language": self._by("language"),
            "by_runtime_mode": self._by("runtime_mode"),
            "by_change_kind": self._by("change_kind"),
            "by_manifest_style": self._by("manifest_style"),
            "cases": [
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "runtime_mode": case.runtime_mode,
                    "change": {
                        "kind": case.change_kind,
                        "path": case.changed_path,
                        "mutation": case.mutation,
                        "absent_from_baseline_observation": case.changed_path_unobserved,
                    },
                    "manifest": {
                        "style": case.manifest_style,
                        "patterns": list(case.manifest_patterns),
                    },
                    "baseline_observation": {
                        "source": OBSERVATION_SOURCE,
                        "complete": case.observation_complete,
                        "paths": list(case.observed_paths),
                        "child_processes": case.observed_child_processes,
                    },
                    "oracle": {
                        "reuse_safe": case.oracle_reuse_safe,
                        "expected_rerun_pass": case.oracle_expected_rerun_pass,
                        "reason": "the changed tracked path was not consumed by the fixture",
                    },
                    "decision": {
                        "reuse": case.decision_reuse,
                        "correct": case.correct_reuse or case.correct_invalidation,
                        "source": DECISION_ENGINE,
                        "current_receipt_available": case.current_receipt_available,
                    },
                    "actual_rerun": asdict(case.actual_rerun),
                    "actual_rerun_matches_oracle": case.actual_rerun_matches_oracle,
                }
                for case in self.cases
            ],
        }

    def text(self) -> str:
        summary = self.summary
        rows = []
        for language, values in self._by("language").items():
            rows.append(
                (
                    language,
                    str(values["total_cases"]),
                    str(values["correct_reuse"]),
                    str(values["over_conservative_rerun"]),
                    str(values["actual_rerun_pass"]),
                )
            )
        return "\n".join(
            [
                "Click unnecessary-rerun benchmark",
                "",
                f"Pinned Click revision: {CLICK_TARGET['commit']}",
                f"Reproducible random seed: {self.seed}",
                f"Total independently generated cases: {summary['total_cases']}",
                "",
                "Plain-language result",
                f"  The fixtures reported {summary['complete_observations']}/{summary['total_cases']} complete baseline observations.",
                f"  The changed tracked path was unobserved in {summary['changed_paths_unobserved']}/{summary['total_cases']} cases.",
                f"  The real fixture still passed in {summary['actual_rerun_pass']}/{summary['total_cases']} cases.",
                f"  Click reused old evidence in {summary['correct_reuse']}/{summary['total_cases']} safe cases.",
                f"  Unnecessary reruns: {summary['over_conservative_rerun']}",
                "",
                "Required result fields",
                f"  Total cases: {summary['total_cases']}",
                f"  Correct reuse: {summary['correct_reuse']}",
                f"  Correct invalidation: {summary['correct_invalidation']} (this safe-only suite has no invalidation cases)",
                f"  Unsafe reuse: {summary['unsafe_reuse']}",
                f"  Over-conservative rerun: {summary['over_conservative_rerun']}",
                "",
                _table(
                    ("language", "cases", "reused", "extra reruns", "real rerun passed"),
                    rows,
                ),
                "",
                "What this proves",
                "  Case generation does not import Click rules. Each changed file is tracked",
                "  but absent from the complete fixture observation, and a real rerun confirms",
                "  that behavior remains passing. This measures missed safe-reuse opportunities,",
                "  not dependency-omission safety.",
            ]
        )


def _table(headers: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    output = [
        "  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "  " + "  ".join("-" * width for width in widths),
    ]
    output.extend(
        "  " + "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(output)


def _evaluate_case(
    case: SafeChangeCase,
    root: Path,
    workspace: Path,
    tools: RuntimeTools,
    java_container: str,
) -> SafeChangeResult:
    root.mkdir(parents=True)
    plan = materialize_safe_change(case, root)
    checks = _checks(case, root, workspace, tools, java_container)
    baseline_run, baseline_output = _run_checks(root, checks)
    if not baseline_run.passed:
        raise RuntimeError(f"baseline fixture failed for {case.case_id}:\n{baseline_output[-4000:]}")
    observation = parse_observation(baseline_output)
    changed_path_unobserved = plan.changed_path not in observation.paths
    if not changed_path_unobserved:
        raise RuntimeError(f"safe change was consumed by fixture: {case.case_id}")
    patterns = manifest_patterns(case, plan)
    _write_manifest(root, checks, patterns)

    _run_git(root, "init", "--quiet")
    _run_git(root, "config", "gc.auto", "0")
    _run_git(root, "add", "-A")
    _run_git(
        root,
        "-c",
        "user.name=Click Safe Change Benchmark",
        "-c",
        "user.email=click-safe-change@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "baseline",
    )

    product_observation = _observed_receipt(observation)
    grouped = {"source": checks}
    baseline_receipt = click_dependency_cache.receipts_for_groups(
        root,
        grouped,
        observations={"source": product_observation},
        git_capture=click_verification.git_capture,
    ).get("source")
    if baseline_receipt is None:
        raise RuntimeError(f"Click did not create a baseline receipt: {case.case_id}")
    environment = os.environ.copy()
    environment["PWD"] = str(root.resolve())
    environment_digest = click_verification.environment_digest(
        checks, cwd=root, environment=environment
    )
    tree = click_verification.git_workspace_snapshot(root)
    if not environment_digest or tree is None:
        raise RuntimeError(f"could not bind baseline execution: {case.case_id}")
    source, group_digest = _source(
        root,
        checks,
        baseline_receipt,
        environment_digest,
        str(tree["digest"]),
    )

    mutation = mutate_safe_path(case, root, plan.changed_path)
    current_receipt = click_dependency_cache.receipts_for_groups(
        root,
        grouped,
        observations={"source": product_observation},
        git_capture=click_verification.git_capture,
    ).get("source")
    decision_reuse = click_verification.dependency_receipt_matches(
        source,
        current_receipt,
        contract_digest=CONTRACT_DIGEST,
        revision=1,
        group_digest=group_digest,
        git_root=str(root.resolve()),
        environment_digest=environment_digest,
        host_coverage=HOST_COVERAGE,
    )
    actual_rerun, _rerun_output = _run_checks(root, checks)
    return SafeChangeResult(
        case_id=case.case_id,
        language=case.language,
        runtime_mode=case.mode,
        change_kind=case.change_kind,
        changed_path=plan.changed_path,
        mutation=mutation,
        manifest_style=case.manifest_style,
        manifest_patterns=patterns,
        observed_paths=observation.paths,
        observed_child_processes=observation.child_processes,
        baseline_passed=baseline_run.passed,
        observation_complete=click_dependency_cache.dependency_observation_is_complete(
            product_observation
        ),
        changed_path_unobserved=changed_path_unobserved,
        current_receipt_available=current_receipt is not None,
        oracle_reuse_safe=True,
        oracle_expected_rerun_pass=True,
        decision_reuse=decision_reuse,
        actual_rerun=actual_rerun,
    )


def run_benchmark(
    *,
    seed: int = DEFAULT_SEED,
    languages: Sequence[str] = LANGUAGES,
    allow_java_pull: bool = False,
    cases: Sequence[SafeChangeCase] | None = None,
) -> UnnecessaryRerunReport:
    selected_cases = tuple(cases) if cases is not None else generate_cases(seed, languages)
    selected_languages = tuple(
        language for language in LANGUAGES if any(case.language == language for case in selected_cases)
    )
    if not selected_cases:
        raise ValueError("unnecessary-rerun benchmark requires at least one case")
    tools = _resolve_tools(set(selected_languages), allow_java_pull=allow_java_pull)
    results: list[SafeChangeResult] = []
    with tempfile.TemporaryDirectory(prefix="click-unnecessary-rerun-") as temporary:
        workspace = Path(temporary)
        java_container = ""
        try:
            if "java" in selected_languages and tools.java_backend == "docker-temurin-21":
                java_container = _start_java_container(workspace, tools)
            for case in selected_cases:
                results.append(
                    _evaluate_case(
                        case,
                        workspace / "cases" / case.case_id,
                        workspace,
                        tools,
                        java_container,
                    )
                )
        finally:
            _stop_java_container(java_container, tools)
    return UnnecessaryRerunReport(seed, tuple(results), tools.versions)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--language",
        action="append",
        choices=LANGUAGES,
        default=[],
        help="run one language; may be repeated (default: all four)",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--pull-java-image", action="store_true")
    parser.add_argument("--fail-on-unnecessary-rerun", action="store_true")
    parser.add_argument("--fail-on-oracle-mismatch", action="store_true")
    arguments = parser.parse_args(argv)
    report = run_benchmark(
        seed=arguments.seed,
        languages=arguments.language or LANGUAGES,
        allow_java_pull=arguments.pull_java_image,
    )
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if arguments.output_json:
        arguments.output_json.parent.mkdir(parents=True, exist_ok=True)
        arguments.output_json.write_text(payload + "\n", encoding="utf-8")
    print(payload if arguments.json else report.text())
    if arguments.fail_on_unnecessary_rerun and report.over_conservative_rerun:
        return 1
    if arguments.fail_on_oracle_mismatch and report.oracle_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
