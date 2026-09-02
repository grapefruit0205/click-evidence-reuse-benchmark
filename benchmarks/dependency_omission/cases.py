"""Generate omission cases without importing Click or its decision rules."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random
from typing import Sequence


DEFAULT_SEED = 20260902
LANGUAGES = ("python", "node", "c", "java")
MODES = (
    "direct-file",
    "nested-pointer",
    "directory-membership",
    "missing-file",
    "child-process",
)
CASES_PER_LANGUAGE = 25


@dataclass(frozen=True)
class OmissionCase:
    case_id: str
    language: str
    mode: str
    variant: int
    token: str
    omission_selector: int


def generate_cases(
    seed: int = DEFAULT_SEED,
    languages: Sequence[str] = LANGUAGES,
) -> tuple[OmissionCase, ...]:
    """Return 25 seeded cases per selected language in seeded order."""
    requested = tuple(languages)
    unknown = set(requested) - set(LANGUAGES)
    if unknown:
        raise ValueError(f"unknown omission benchmark languages: {sorted(unknown)}")
    if len(requested) != len(set(requested)):
        raise ValueError("languages must not contain duplicates")

    cases: list[OmissionCase] = []
    for language in requested:
        local = random.Random(f"click-omission-v1:{seed}:{language}")
        language_cases: list[OmissionCase] = []
        for variant in range(5):
            for mode in MODES:
                token = hashlib.sha256(
                    f"{seed}:{language}:{mode}:{variant}:{local.getrandbits(64)}".encode()
                ).hexdigest()[:12]
                language_cases.append(
                    OmissionCase(
                        case_id=f"{language}-{mode}-{variant + 1:02d}-{token}",
                        language=language,
                        mode=mode,
                        variant=variant,
                        token=token,
                        omission_selector=local.getrandbits(16),
                    )
                )
        local.shuffle(language_cases)
        cases.extend(language_cases)

    order = random.Random(f"click-omission-v1:{seed}:order")
    order.shuffle(cases)
    return tuple(cases)


assert len(generate_cases()) == len(LANGUAGES) * CASES_PER_LANGUAGE
