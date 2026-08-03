"""Build the project wheel and download exact Debian 13 arm64 runtime wheels."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    build_environment = {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "SOURCE_DATE_EPOCH": "1767225600",
    }

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--no-deps",
            "--no-cache-dir",
            "--dest",
            str(output),
            "--platform=manylinux_2_34_aarch64",
            "--platform=manylinux2014_aarch64",
            "--platform=any",
            "--implementation=cp",
            "--python-version=313",
            "--abi=cp313",
            "--requirement",
            str(root / "requirements" / "runtime-arm64.lock"),
        ],
        check=True,
        cwd=root,
        env=build_environment,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--ignore-requires-python",
            "--no-deps",
            "--no-cache-dir",
            "--wheel-dir",
            str(output),
            ".",
        ],
        check=True,
        cwd=root,
        env=build_environment,
    )
    shutil.copy2(root / "requirements" / "runtime-arm64.lock", output / "runtime-arm64.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
