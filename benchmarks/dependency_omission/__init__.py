"""Independent runtime-discovered dependency-omission benchmark."""

from __future__ import annotations

from typing import Any


def run_benchmark(*args: Any, **kwargs: Any) -> Any:
    """Import the runner lazily so catalog tests need no Click checkout."""
    from .runner import run_benchmark as _run_benchmark

    return _run_benchmark(*args, **kwargs)


__all__ = ["run_benchmark"]
