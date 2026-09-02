from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def mark(path: str) -> None:
    print(f"CLICK_BENCH_DEP={path}", flush=True)


def read_text(path: str) -> str | None:
    mark(path)
    try:
        return Path(path.rstrip("/")).read_text(encoding="utf-8")
    except OSError:
        return None


def parse_spec() -> dict[str, str]:
    value = read_text("case.spec")
    if value is None:
        return {}
    return dict(line.split("=", 1) for line in value.splitlines() if "=" in line)


def child(path: str, expected: str) -> int:
    return 0 if read_text(path) == expected else 1


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        return child(sys.argv[2], sys.argv[3])
    spec = parse_spec()
    if read_text("stable.txt") != "stable-control":
        return 1
    mode = spec.get("mode")
    expected = spec.get("expected", "")
    if mode == "direct-file":
        return 0 if read_text(spec["target"]) == expected else 1
    if mode == "nested-pointer":
        target = read_text(spec["pointer"])
        return 0 if target is not None and read_text(target) == expected else 1
    if mode == "directory-membership":
        target = spec["target"]
        mark(target)
        try:
            names = sorted(path.name for path in Path(target.rstrip("/")).iterdir())
        except OSError:
            return 1
        return 0 if names == ["expected.txt"] else 1
    if mode == "missing-file":
        target = spec["target"]
        mark(target)
        return 0 if not Path(target).exists() else 1
    if mode == "child-process":
        completed = subprocess.run(
            [sys.executable, __file__, "--child", spec["target"], expected],
            check=False,
        )
        print("CLICK_BENCH_CHILD=1", flush=True)
        return completed.returncode
    return 1


raise SystemExit(main())
