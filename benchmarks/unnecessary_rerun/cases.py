"""Generate safe-change cases without importing Click or its rules."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Sequence


DEFAULT_SEED = 20260903
LANGUAGES = ("python", "node", "c", "java")
RUNTIME_MODES = (
    "direct-file",
    "nested-pointer",
    "directory-membership",
    "missing-file",
    "child-process",
)
CHANGE_KINDS = (
    "documentation",
    "unused-example",
    "unread-asset",
    "tooling-note",
    "unrelated-source",
)
MANIFEST_STYLES = (
    "exact-controls",
    "runtime-envelope",
    "repository-wide",
    "mixed-envelopes",
    "language-envelope",
)
CASES_PER_LANGUAGE = 25


@dataclass(frozen=True)
class SafeChangeCase:
    case_id: str
    language: str
    mode: str
    change_kind: str
    manifest_style: str
    variant: int
    token: str
    omission_selector: int = 0


def generate_cases(
    seed: int = DEFAULT_SEED,
    languages: Sequence[str] = LANGUAGES,
) -> tuple[SafeChangeCase, ...]:
    requested = tuple(languages)
    unknown = set(requested) - set(LANGUAGES)
    if unknown:
        raise ValueError(f"unknown unnecessary-rerun languages: {sorted(unknown)}")
    if len(requested) != len(set(requested)):
        raise ValueError("languages must not contain duplicates")

    cases: list[SafeChangeCase] = []
    for language in requested:
        local = random.Random(f"click-safe-change-v1:{seed}:{language}")
        language_cases: list[SafeChangeCase] = []
        for mode_index, mode in enumerate(RUNTIME_MODES):
            for change_index, change_kind in enumerate(CHANGE_KINDS):
                token = hashlib.sha256(
                    f"{seed}:{language}:{mode}:{change_kind}:{local.getrandbits(64)}".encode()
                ).hexdigest()[:12]
                language_cases.append(
                    SafeChangeCase(
                        case_id=(
                            f"{language}-{mode}-{change_kind}-{token}"
                        ),
                        language=language,
                        mode=mode,
                        change_kind=change_kind,
                        manifest_style=MANIFEST_STYLES[change_index],
                        variant=(mode_index + change_index) % 5,
                        token=token,
                    )
                )
        local.shuffle(language_cases)
        cases.extend(language_cases)

    order = random.Random(f"click-safe-change-v1:{seed}:order")
    order.shuffle(cases)
    return tuple(cases)


assert len(generate_cases()) == len(LANGUAGES) * CASES_PER_LANGUAGE
