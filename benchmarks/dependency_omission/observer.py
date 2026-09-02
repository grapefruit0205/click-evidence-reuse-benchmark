"""Parse dependency events emitted by the black-box fixture processes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


DEPENDENCY_PREFIX = "CLICK_BENCH_DEP="
CHILD_PREFIX = "CLICK_BENCH_CHILD="
OBSERVATION_SOURCE = "fixture-self-report-v1"


@dataclass(frozen=True)
class FixtureObservation:
    paths: tuple[str, ...]
    child_processes: int


def _valid_relative_path(value: str) -> bool:
    candidate = value[:-1] if value.endswith("/") else value
    path = PurePosixPath(candidate)
    return bool(
        candidate
        and "\\" not in candidate
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def parse_observation(output: str) -> FixtureObservation:
    paths: set[str] = set()
    child_processes = 0
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith(DEPENDENCY_PREFIX):
            relative = line[len(DEPENDENCY_PREFIX) :]
            if not _valid_relative_path(relative):
                raise ValueError(f"fixture emitted an invalid dependency path: {relative!r}")
            paths.add(relative)
        elif line.startswith(CHILD_PREFIX):
            try:
                count = int(line[len(CHILD_PREFIX) :])
            except ValueError as error:
                raise ValueError("fixture emitted an invalid child-process count") from error
            if count < 0:
                raise ValueError("fixture emitted a negative child-process count")
            child_processes += count
    if not paths:
        raise ValueError("fixture emitted no dependency events")
    return FixtureObservation(tuple(sorted(paths)), child_processes)
