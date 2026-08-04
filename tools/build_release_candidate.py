"""Build and verify a reproducible Phase 1 LoxBerry release candidate."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(*arguments: str, root: Path, environment: dict[str, str] | None = None) -> None:
    subprocess.run(arguments, check=True, cwd=root, env=environment)


def _version(root: Path) -> str:
    parser = configparser.ConfigParser()
    parser.read(root / "plugin.cfg", encoding="utf-8")
    return parser["PLUGIN"]["VERSION"]


def _normalized_name(value: str) -> str:
    import re

    return re.sub(r"[-_.]+", "-", value).lower()


def _locked_requirements(path: Path) -> dict[str, str]:
    import re

    requirements: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if match:
            requirements[_normalized_name(match.group(1))] = match.group(2).lower()
    return requirements


def _wheel_identity(path: Path) -> tuple[str, str] | None:
    parts = path.name.removesuffix(".whl").split("-")
    if len(parts) < 5:
        return None
    return _normalized_name(parts[0]), parts[1].lower()


def _copy_runtime_wheels(source: Path, destination: Path, requirements: dict[str, str]) -> None:
    if not source.is_dir():
        raise RuntimeError("runtime wheelhouse does not exist")
    copied: list[tuple[str, str]] = []
    for wheel in source.glob("*.whl"):
        identity = _wheel_identity(wheel)
        if identity is not None and identity in requirements.items():
            shutil.copy2(wheel, destination / wheel.name)
            copied.append(identity)
    if len(copied) != len(set(copied)) or set(copied) != set(requirements.items()):
        raise RuntimeError("runtime wheelhouse does not exactly satisfy the lock")


def _build_project_wheel(root: Path, wheelhouse: Path, environment: dict[str, str]) -> None:
    _run(
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--ignore-requires-python",
        "--no-deps",
        "--no-cache-dir",
        "--wheel-dir",
        str(wheelhouse),
        ".",
        root=root,
        environment=environment,
    )


def _publish(candidate: Path, output: Path, digest: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() != digest:
        raise RuntimeError("release output already exists with different content")
    if not output.exists():
        temporary = output.with_name(f".{output.name}.tmp")
        shutil.copy2(candidate, temporary)
        os.replace(temporary, output)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii", newline="\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--runtime-wheelhouse",
        type=Path,
        help="Reuse cached arm64 dependency wheels; the project wheel is always rebuilt.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONPATH": str(root / "src"),
        "SOURCE_DATE_EPOCH": "1767225600",
    }

    _run(sys.executable, "tools/test.py", root=root, environment=environment)
    with tempfile.TemporaryDirectory(prefix="mcpserver-release-", dir=output_dir) as temporary:
        work = Path(temporary)
        wheelhouse = work / "wheelhouse"
        wheelhouse.mkdir()
        if args.runtime_wheelhouse is None:
            _run(
                sys.executable,
                "tools/prepare_wheelhouse.py",
                str(wheelhouse),
                root=root,
                environment=environment,
            )
        else:
            requirements = _locked_requirements(root / "requirements" / "runtime-arm64.lock")
            _copy_runtime_wheels(args.runtime_wheelhouse.resolve(), wheelhouse, requirements)
            _build_project_wheel(root, wheelhouse, environment)

        first = work / "candidate-a.zip"
        second = work / "candidate-b.zip"
        for candidate in (first, second):
            _run(
                sys.executable,
                "tools/build_plugin.py",
                "--wheelhouse",
                str(wheelhouse),
                "--output",
                str(candidate),
                root=root,
                environment=environment,
            )
        first_digest = hashlib.sha256(first.read_bytes()).hexdigest()
        second_digest = hashlib.sha256(second.read_bytes()).hexdigest()
        if first_digest != second_digest:
            raise RuntimeError("repeated plugin builds are not byte-identical")

        output = output_dir / f"LoxBerry-MCP-Server-{_version(root)}.zip"
        _publish(first, output, first_digest)
        _run(
            sys.executable,
            "tools/verify_plugin.py",
            str(output),
            root=root,
            environment=environment,
        )

    print(f"RELEASE_CANDIDATE=pass path={output}")
    print(f"SHA256={first_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
