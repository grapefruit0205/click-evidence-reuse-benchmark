from __future__ import annotations

import unittest

from run_benchmark import normalize_repository, validate_ref


class PublicRunnerTests(unittest.TestCase):
    def test_repository_accepts_owner_name_or_github_https_url(self) -> None:
        expected = "https://github.com/grapefruit0205/click.git"
        self.assertEqual(normalize_repository("grapefruit0205/click"), expected)
        self.assertEqual(
            normalize_repository("https://github.com/grapefruit0205/click.git"),
            expected,
        )

    def test_repository_and_ref_reject_shell_or_transport_ambiguity(self) -> None:
        for repository in ("git@github.com:owner/repo", "owner/repo;echo", "../repo"):
            with self.subTest(repository=repository):
                with self.assertRaises(ValueError):
                    normalize_repository(repository)
        for target_ref in ("", "--upload-pack=tool", "main branch", "main\nother"):
            with self.subTest(target_ref=target_ref):
                with self.assertRaises(ValueError):
                    validate_ref(target_ref)


if __name__ == "__main__":
    unittest.main()
