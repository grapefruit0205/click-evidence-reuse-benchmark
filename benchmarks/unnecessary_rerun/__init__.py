"""Independent benchmark for unnecessary verification reruns."""

from __future__ import annotations

from typing import Any


def run_benchmark(*args: Any, **kwargs: Any) -> Any:
    from .runner import run_benchmark as _run_benchmark

    return _run_benchmark(*args, **kwargs)


__all__ = ["run_benchmark"]
