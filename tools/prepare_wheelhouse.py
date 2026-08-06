"""Prepare exact Debian 13 arm64 wheels for packaging or a runtime cache."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _verify_runtime_wheels(output: Path, hash_lock: Path) -> None:
    expected = {}
    for line in hash_lock.read_text(encoding="ascii").splitlines():
        digest, filename = line.split("  ", 1)
        expected[filename] = digest
    actual = {
        wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest() for wheel in output.glob("*.whl")
    }
    if actual != expected:
        raise RuntimeError("downloaded runtime wheels do not match runtime-arm64.sha256")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="Download only the pinned arm64 runtime wheels for a reusable cache.",
    )
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
    _verify_runtime_wheels(output, root / "requirements" / "runtime-arm64.sha256")
    if not args.runtime_only:
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
    shutil.copy2(
        root / "requirements" / "runtime-arm64.sha256",
        output / "runtime-arm64.sha256",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
