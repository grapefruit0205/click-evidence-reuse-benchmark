"""Run 100 black-box dependency-omission cases against Click."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Sequence

from benchmarks.evidence_reuse.click_target import configure_click_target

from .cases import DEFAULT_SEED, LANGUAGES, OmissionCase, generate_cases
from .fixture import FixturePlan, materialize, mutate_omitted_dependency
from .observer import OBSERVATION_SOURCE, FixtureObservation, parse_observation


CLICK_ROOT, CLICK_TARGET = configure_click_target()

from hooks import (
    click_dependency_cache,
    click_evidence,
    click_host_coverage,
    click_verification,
)


DECISION_ENGINE = "hooks.click_verification.dependency_receipt_matches"
CONTRACT_DIGEST = hashlib.sha256(b"dependency-omission-black-box-v1").hexdigest()
HOST_COVERAGE = click_host_coverage.receipt("codex")
JAVA_IMAGE_TAG = "eclipse-temurin:21-jdk-alpine"
JAVA_IMAGE = (
    "eclipse-temurin:21-jdk-alpine@"
    "sha256:6ea5548706b60ac0a602eaf48af74792cbab012d90e811ca8db6184b16b5c3d6"
)


@dataclass(frozen=True)
class RuntimeTools:
    python: str
    node: str = ""
    gcc: str = ""
    javac: str = ""
    java: str = ""
    docker: str = ""
    java_backend: str = ""
    versions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    ran: bool
    passed: bool
    exit_code: int
    failed_check: int | None = None


@dataclass(frozen=True)
class OmissionCaseResult:
    case_id: str
    language: str
    mode: str
    omitted_dependency: str
    mutation: str
    manifest_paths: tuple[str, ...]
    observed_paths: tuple[str, ...]
    observed_child_processes: int
    baseline_passed: bool
    observation_complete: bool
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


def _metrics(cases: Iterable[OmissionCaseResult]) -> dict[str, Any]:
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
        "actual_rerun_pass": sum(case.actual_rerun.passed for case in selected),
        "actual_rerun_fail": sum(not case.actual_rerun.passed for case in selected),
        "actual_rerun_oracle_mismatch": sum(
            not case.actual_rerun_matches_oracle for case in selected
        ),
        "complete_observations": sum(case.observation_complete for case in selected),
        "manifest_omissions": sum(
            case.omitted_dependency not in case.manifest_paths for case in selected
        ),
        "current_receipts_available": sum(
            case.current_receipt_available for case in selected
        ),
    }


@dataclass(frozen=True)
class OmissionBenchmarkReport:
    seed: int
    cases: tuple[OmissionCaseResult, ...]
    toolchains: tuple[tuple[str, str], ...]

    @property
    def summary(self) -> dict[str, Any]:
        return _metrics(self.cases)

    @property
    def unsafe_reuse(self) -> int:
        return int(self.summary["unsafe_reuse"])

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
            "suite": "dependency-omission-100",
            "seed": self.seed,
            "decision_engine": DECISION_ENGINE,
            "click_target": CLICK_TARGET,
            "observation_source": OBSERVATION_SOURCE,
            "oracle_source": "observed-dependency mutation plus fixture behavior contract",
            "toolchains": dict(self.toolchains),
            "by_language": self._by("language"),
            "by_mode": self._by("mode"),
            "cases": [
                {
                    "case_id": case.case_id,
                    "language": case.language,
                    "mode": case.mode,
                    "manifest": {
                        "deliberately_incomplete": True,
                        "omitted_dependency": case.omitted_dependency,
                        "paths": list(case.manifest_paths),
                    },
                    "baseline_observation": {
                        "source": OBSERVATION_SOURCE,
                        "complete": case.observation_complete,
                        "paths": list(case.observed_paths),
                        "child_processes": case.observed_child_processes,
                    },
                    "mutation": case.mutation,
                    "oracle": {
                        "reuse_safe": case.oracle_reuse_safe,
                        "expected_rerun_pass": case.oracle_expected_rerun_pass,
                        "reason": "a dependency proven consumed at baseline was omitted and changed",
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
                    str(values["correct_invalidation"]),
                    str(values["unsafe_reuse"]),
                    str(values["actual_rerun_fail"]),
                )
            )
        lines = [
            "Click dependency-omission benchmark",
            "",
            f"Pinned Click revision: {CLICK_TARGET['commit']}",
            f"Reproducible random seed: {self.seed}",
            f"Total independently generated cases: {summary['total_cases']}",
            "",
            "Plain-language result",
            f"  The fixtures reported {summary['complete_observations']}/{summary['total_cases']} complete baseline observations.",
            f"  The manifest omitted one proven runtime dependency in {summary['manifest_omissions']}/{summary['total_cases']} cases.",
            f"  After that omitted dependency changed, the real fixture failed in {summary['actual_rerun_fail']}/{summary['total_cases']} cases.",
            f"  Click rejected old evidence in {summary['correct_invalidation']}/{summary['total_cases']} cases.",
            f"  Unsafe old-result reuse: {summary['unsafe_reuse']}",
            "",
            "Required result fields",
            f"  Total cases: {summary['total_cases']}",
            f"  Correct reuse: {summary['correct_reuse']} (this omission-only suite has no safe-reuse cases)",
            f"  Correct invalidation: {summary['correct_invalidation']}",
            f"  Unsafe reuse: {summary['unsafe_reuse']}",
            f"  Over-conservative rerun: {summary['over_conservative_rerun']}",
            "",
            _table(
                ("language", "cases", "invalidated", "unsafe", "real rerun failed"),
                rows,
            ),
            "",
            "What this proves",
            "  Cases are generated without importing Click rules. The running fixture reports",
            "  what it consumed; the harness then omits and mutates one of those paths.",
            "  A score of 100% here means all tested omissions were caught. It is not a claim",
            "  that every dependency in every production repository can always be observed.",
        ]
        return "\n".join(lines)


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


def _capture_first_line(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
    output = (result.stdout + result.stderr).strip().splitlines()
    return output[0] if output else "unknown"


def _resolve_tools(languages: set[str], *, allow_java_pull: bool) -> RuntimeTools:
    python = str(Path(sys.executable).resolve())
    node = shutil.which("node") or ""
    gcc = shutil.which("gcc") or ""
    javac = shutil.which("javac") or ""
    java = shutil.which("java") or ""
    docker = shutil.which("docker") or ""
    versions = {"python": _capture_first_line([python, "--version"])}

    if "node" in languages:
        if not node:
            raise RuntimeError("Node.js is required for Node omission cases")
        versions["node"] = _capture_first_line([node, "--version"])
    if "c" in languages:
        if not gcc:
            raise RuntimeError("GCC is required for C omission cases")
        versions["gcc"] = _capture_first_line([gcc, "--version"])

    java_backend = ""
    if "java" in languages:
        if javac and java:
            java_backend = "native-jdk"
            versions["java"] = _capture_first_line([java, "-version"])
        elif docker:
            inspect = subprocess.run(
                [docker, "image", "inspect", JAVA_IMAGE],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if inspect.returncode != 0 and allow_java_pull:
                pull = subprocess.run(
                    [docker, "pull", JAVA_IMAGE],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300,
                )
                if pull.returncode != 0:
                    raise RuntimeError(f"could not pull the pinned Java image: {pull.stderr.strip()}")
                inspect = subprocess.run(
                    [docker, "image", "inspect", JAVA_IMAGE],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
            if inspect.returncode != 0:
                raise RuntimeError(
                    "Java requires javac/java or the pinned Docker image; use --pull-java-image"
                )
            java_backend = "docker-temurin-21"
            versions["java"] = f"Temurin JDK 21 ({JAVA_IMAGE.split('@', 1)[1]})"
            versions["docker"] = _capture_first_line([docker, "--version"])
        else:
            raise RuntimeError("Java requires javac/java or Docker")

    return RuntimeTools(
        python=python,
        node=node,
        gcc=gcc,
        javac=javac,
        java=java,
        docker=docker,
        java_backend=java_backend,
        versions=tuple(sorted(versions.items())),
    )


def _start_java_container(workspace: Path, tools: RuntimeTools) -> str:
    suffix = hashlib.sha256(str(workspace).encode()).hexdigest()[:10]
    name = f"click-omission-java-{os.getpid()}-{suffix}"
    command = [
        tools.docker,
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
    ]
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        command.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    command.extend(
        [
            "--mount",
            f"type=bind,src={workspace.resolve()},dst=/benchmark",
            JAVA_IMAGE,
            "tail",
            "-f",
            "/dev/null",
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"could not start Java container: {result.stderr.strip()}")
    return name


def _stop_java_container(name: str, tools: RuntimeTools) -> None:
    if name:
        subprocess.run(
            [tools.docker, "stop", "--time", "1", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )


def _checks(
    case: OmissionCase,
    root: Path,
    workspace: Path,
    tools: RuntimeTools,
    java_container: str,
) -> list[dict[str, Any]]:
    def check(argv: list[str]) -> dict[str, Any]:
        return {"evidence_id": "omission-check", "argv": argv, "class": "targeted"}

    if case.language == "python":
        return [check([tools.python, "omission_check.py"])]
    if case.language == "node":
        return [check([tools.node, "omission_check.js"])]
    if case.language == "c":
        executable = "build/omission_check.exe" if os.name == "nt" else "build/omission_check"
        run_executable = str((root / executable).resolve()) if os.name == "nt" else f"./{executable}"
        return [
            check(
                [
                    tools.gcc,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "omission_check.c",
                    "-o",
                    executable,
                ]
            ),
            check([run_executable]),
        ]
    if case.language == "java" and tools.java_backend == "native-jdk":
        return [
            check([tools.javac, "-d", "build", "OmissionCheck.java"]),
            check([tools.java, "-cp", "build", "OmissionCheck"]),
        ]
    if case.language == "java" and tools.java_backend == "docker-temurin-21":
        relative = root.relative_to(workspace).as_posix()
        container_root = f"/benchmark/{relative}"
        return [
            check(
                [
                    tools.docker,
                    "exec",
                    "--workdir",
                    container_root,
                    java_container,
                    "javac",
                    "-d",
                    "build",
                    "OmissionCheck.java",
                ]
            ),
            check(
                [
                    tools.docker,
                    "exec",
                    "--workdir",
                    container_root,
                    java_container,
                    "java",
                    "-cp",
                    "build",
                    "OmissionCheck",
                ]
            ),
        ]
    raise RuntimeError(f"unsupported language: {case.language}")


def _run_checks(root: Path, checks: list[dict[str, Any]]) -> tuple[ExecutionResult, str]:
    (root / "build").mkdir(exist_ok=True)
    outputs = []
    for index, check in enumerate(checks):
        try:
            result = subprocess.run(
                check["argv"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
        except subprocess.TimeoutExpired as error:
            outputs.extend([str(error.stdout or ""), str(error.stderr or "")])
            return ExecutionResult(True, False, 124, index), "\n".join(outputs)
        outputs.extend([result.stdout, result.stderr])
        if result.returncode != 0:
            return ExecutionResult(True, False, result.returncode, index), "\n".join(outputs)
    return ExecutionResult(True, True, 0), "\n".join(outputs)


def _write_manifest(root: Path, checks: list[dict[str, Any]], paths: tuple[str, ...]) -> None:
    manifest = {
        "version": 1,
        "entries": [{"checks": [check["argv"] for check in checks], "paths": list(paths)}],
    }
    target = root / ".click" / "evidence-dependencies.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _run_git(root: Path, *arguments: str) -> None:
    result = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")


def _source(
    root: Path,
    checks: list[dict[str, Any]],
    receipt: dict[str, Any],
    environment_digest: str,
    tree_digest: str,
) -> tuple[dict[str, Any], str]:
    state = click_evidence.fresh_state(
        {"verification": {"evidence": [{"id": "omission-check", "kind": "argv"}]}}
    )
    source = state["sources"][click_evidence.evidence_key("omission-check")]
    group_digest = click_verification.group_digest(checks)
    source.update(
        {
            "status": "stale",
            "verified_revision": 0,
            "verified_contract_digest": CONTRACT_DIGEST,
            "verified_check_digest": group_digest,
            "verified_root": str(root.resolve()),
            "verified_tree_digest": tree_digest,
            "verified_environment_digest": environment_digest,
            "verified_executable_digest": hashlib.sha256(
                json.dumps([check["argv"] for check in checks]).encode()
            ).hexdigest(),
            "verified_host_coverage": HOST_COVERAGE,
            "verified_at": 1,
        }
    )
    click_verification.store_dependency_receipt(source, receipt)
    return source, group_digest


def _observed_receipt(observation: FixtureObservation) -> dict[str, Any]:
    return click_dependency_cache.dependency_observation(
        observation.paths,
        child_processes=observation.child_processes,
        process_tree_complete=True,
    )


def _manifest_paths(
    root: Path,
    plan: FixturePlan,
    observation: FixtureObservation,
    omitted: str,
) -> tuple[str, ...]:
    candidates = {plan.source_path, "case.spec", "stable.txt"}
    candidates.update(path for path in observation.paths if path != omitted)
    paths = tuple(sorted(candidates))
    for relative in paths:
        if not (root / relative.rstrip("/")).exists():
            raise RuntimeError(f"manifest path does not exist: {relative}")
    if omitted in paths:
        raise RuntimeError("omitted dependency leaked into the manifest")
    return paths


def _evaluate_case(
    case: OmissionCase,
    root: Path,
    workspace: Path,
    tools: RuntimeTools,
    java_container: str,
) -> OmissionCaseResult:
    root.mkdir(parents=True)
    plan = materialize(case, root)
    checks = _checks(case, root, workspace, tools, java_container)
    baseline_run, baseline_output = _run_checks(root, checks)
    if not baseline_run.passed:
        raise RuntimeError(f"baseline fixture failed for {case.case_id}:\n{baseline_output[-4000:]}")
    observation = parse_observation(baseline_output)
    if not {"case.spec", "stable.txt"}.issubset(observation.paths):
        raise RuntimeError(f"fixture omitted control observations: {case.case_id}")
    mutable_observed = tuple(
        path for path in plan.mutable_paths if path in observation.paths
    )
    if len(mutable_observed) != len(plan.mutable_paths):
        raise RuntimeError(f"fixture did not report every mutable dependency: {case.case_id}")
    omitted = mutable_observed[case.omission_selector % len(mutable_observed)]
    manifest_paths = _manifest_paths(root, plan, observation, omitted)
    _write_manifest(root, checks, manifest_paths)

    _run_git(root, "init", "--quiet")
    _run_git(root, "config", "gc.auto", "0")
    _run_git(root, "add", "-A")
    _run_git(
        root,
        "-c",
        "user.name=Click Omission Benchmark",
        "-c",
        "user.email=click-omission@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "baseline",
    )

    product_observation = _observed_receipt(observation)
    grouped = {"source": checks}
    receipts = click_dependency_cache.receipts_for_groups(
        root,
        grouped,
        observations={"source": product_observation},
        git_capture=click_verification.git_capture,
    )
    baseline_receipt = receipts.get("source")
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

    mutation = mutate_omitted_dependency(case, plan, root, omitted)
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
    return OmissionCaseResult(
        case_id=case.case_id,
        language=case.language,
        mode=case.mode,
        omitted_dependency=omitted,
        mutation=mutation,
        manifest_paths=manifest_paths,
        observed_paths=observation.paths,
        observed_child_processes=observation.child_processes,
        baseline_passed=baseline_run.passed,
        observation_complete=click_dependency_cache.dependency_observation_is_complete(
            product_observation
        ),
        current_receipt_available=current_receipt is not None,
        oracle_reuse_safe=False,
        oracle_expected_rerun_pass=False,
        decision_reuse=decision_reuse,
        actual_rerun=actual_rerun,
    )


def run_benchmark(
    *,
    seed: int = DEFAULT_SEED,
    languages: Sequence[str] = LANGUAGES,
    allow_java_pull: bool = False,
    cases: Sequence[OmissionCase] | None = None,
) -> OmissionBenchmarkReport:
    selected_cases = tuple(cases) if cases is not None else generate_cases(seed, languages)
    selected_languages = tuple(
        language for language in LANGUAGES if any(case.language == language for case in selected_cases)
    )
    if not selected_cases:
        raise ValueError("dependency-omission benchmark requires at least one case")
    tools = _resolve_tools(set(selected_languages), allow_java_pull=allow_java_pull)
    results: list[OmissionCaseResult] = []
    with tempfile.TemporaryDirectory(prefix="click-dependency-omission-") as temporary:
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
    return OmissionBenchmarkReport(seed, tuple(results), tools.versions)


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
    parser.add_argument("--fail-on-unsafe", action="store_true")
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
    if arguments.fail_on_unsafe and report.unsafe_reuse:
        return 1
    if arguments.fail_on_oracle_mismatch and report.oracle_mismatch:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
