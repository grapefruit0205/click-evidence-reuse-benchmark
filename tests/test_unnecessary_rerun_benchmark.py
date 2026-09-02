from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import unittest

from benchmarks.unnecessary_rerun.cases import (
    CASES_PER_LANGUAGE,
    CHANGE_KINDS,
    DEFAULT_SEED,
    LANGUAGES,
    MANIFEST_STYLES,
    RUNTIME_MODES,
    generate_cases,
)


class UnnecessaryRerunCatalogTests(unittest.TestCase):
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
            {mode: 20 for mode in RUNTIME_MODES},
        )
        self.assertEqual(
            Counter(case.change_kind for case in cases),
            {kind: 20 for kind in CHANGE_KINDS},
        )
        self.assertEqual(
            Counter(case.manifest_style for case in cases),
            {style: 20 for style in MANIFEST_STYLES},
        )

    def test_seed_is_reproducible_but_changes_the_catalog(self) -> None:
        self.assertEqual(generate_cases(DEFAULT_SEED), generate_cases(DEFAULT_SEED))
        self.assertNotEqual(
            generate_cases(DEFAULT_SEED), generate_cases(DEFAULT_SEED + 1)
        )

    def test_safe_case_layers_do_not_import_click_rules(self) -> None:
        root = Path(__file__).resolve().parents[1] / "benchmarks" / "unnecessary_rerun"
        for name in ("cases.py", "fixture.py"):
            with self.subTest(name=name):
                source = (root / name).read_text(encoding="utf-8")
                self.assertNotIn("from hooks", source)
                self.assertNotIn("click_verification", source)
                self.assertNotIn("click_dependency_cache", source)


def _runtime_available() -> tuple[bool, str]:
    try:
        from benchmarks.dependency_omission.runner import _resolve_tools

        _resolve_tools(set(LANGUAGES), allow_java_pull=False)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return False, str(error)
    return True, ""


RUNTIMES_AVAILABLE, RUNTIME_SKIP_REASON = _runtime_available()


@unittest.skipUnless(RUNTIMES_AVAILABLE, RUNTIME_SKIP_REASON)
class UnnecessaryRerunRuntimeTests(unittest.TestCase):
    def test_real_click_reuses_one_safe_case_per_language(self) -> None:
        from benchmarks.unnecessary_rerun import run_benchmark

        catalog = generate_cases()
        selectors = (
            ("python", "direct-file", "repository-wide"),
            ("node", "nested-pointer", "mixed-envelopes"),
            ("c", "directory-membership", "runtime-envelope"),
            ("java", "child-process", "language-envelope"),
        )
        selected = tuple(
            next(
                case
                for case in catalog
                if (case.language, case.mode, case.manifest_style) == selector
            )
            for selector in selectors
        )
        report = run_benchmark(cases=selected)
        summary = report.summary

        self.assertEqual(summary["total_cases"], 4)
        self.assertEqual(summary["correct_reuse"], 4)
        self.assertEqual(summary["over_conservative_rerun"], 0)
        self.assertEqual(summary["actual_rerun_pass"], 4)
        self.assertEqual(summary["actual_rerun_oracle_mismatch"], 0)
        self.assertEqual(summary["changed_paths_unobserved"], 4)
        self.assertEqual(summary["current_receipts_available"], 4)


if __name__ == "__main__":
    unittest.main()
