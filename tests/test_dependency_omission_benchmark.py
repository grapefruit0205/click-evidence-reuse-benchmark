from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import unittest

from benchmarks.dependency_omission.cases import (
    CASES_PER_LANGUAGE,
    DEFAULT_SEED,
    LANGUAGES,
    MODES,
    generate_cases,
)
from benchmarks.dependency_omission.observer import parse_observation


class DependencyOmissionCatalogTests(unittest.TestCase):
    def test_default_catalog_is_balanced_and_unique(self) -> None:
        cases = generate_cases()

        self.assertEqual(len(cases), 100)
        self.assertEqual(len({case.case_id for case in cases}), 100)
        self.assertEqual(
            Counter(case.language for case in cases),
            {language: CASES_PER_LANGUAGE for language in LANGUAGES},
        )
        self.assertEqual(
            Counter(case.mode for case in cases),
            {mode: 20 for mode in MODES},
        )

    def test_seed_is_reproducible_but_changes_the_catalog(self) -> None:
        first = generate_cases(DEFAULT_SEED)
        second = generate_cases(DEFAULT_SEED)
        different = generate_cases(DEFAULT_SEED + 1)

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_generation_layer_does_not_import_click_rules(self) -> None:
        root = Path(__file__).resolve().parents[1] / "benchmarks" / "dependency_omission"
        for name in ("cases.py", "fixture.py", "observer.py"):
            with self.subTest(name=name):
                source = (root / name).read_text(encoding="utf-8")
                self.assertNotIn("from hooks", source)
                self.assertNotIn("click_verification", source)
                self.assertNotIn("click_dependency_cache", source)

    def test_observer_uses_process_output_not_case_labels(self) -> None:
        observation = parse_observation(
            "noise\nCLICK_BENCH_DEP=stable.txt\n"
            "CLICK_BENCH_DEP=runtime/data.txt\nCLICK_BENCH_CHILD=1\n"
        )

        self.assertEqual(observation.paths, ("runtime/data.txt", "stable.txt"))
        self.assertEqual(observation.child_processes, 1)


def _runtime_available() -> tuple[bool, str]:
    try:
        from benchmarks.dependency_omission.runner import _resolve_tools

        _resolve_tools(set(LANGUAGES), allow_java_pull=False)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return False, str(error)
    return True, ""


RUNTIMES_AVAILABLE, RUNTIME_SKIP_REASON = _runtime_available()


@unittest.skipUnless(RUNTIMES_AVAILABLE, RUNTIME_SKIP_REASON)
class DependencyOmissionRuntimeTests(unittest.TestCase):
    def test_one_black_box_case_per_language_uses_real_click_decision(self) -> None:
        from benchmarks.dependency_omission import run_benchmark

        catalog = generate_cases()
        selected = tuple(
            next(
                case
                for case in catalog
                if case.language == language and case.mode == "direct-file"
            )
            for language in LANGUAGES
        )
        report = run_benchmark(cases=selected)
        summary = report.summary

        self.assertEqual(summary["total_cases"], 4)
        self.assertEqual(summary["correct_invalidation"], 4)
        self.assertEqual(summary["unsafe_reuse"], 0)
        self.assertEqual(summary["actual_rerun_fail"], 4)
        self.assertEqual(summary["actual_rerun_oracle_mismatch"], 0)
        self.assertEqual(summary["manifest_omissions"], 4)
        self.assertEqual(summary["current_receipts_available"], 4)


if __name__ == "__main__":
    unittest.main()
