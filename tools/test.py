"""Run the deterministic checks used locally and in CI."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    commands = (
        (sys.executable, "-m", "ruff", "format", "--check", "."),
        (sys.executable, "-m", "ruff", "check", "."),
        (sys.executable, "-m", "mypy"),
        (sys.executable, "-m", "pytest"),
    )
    for command in commands:
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
