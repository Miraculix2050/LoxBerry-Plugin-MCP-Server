"""Build and verify a reproducible LoxBerry MCP Server release candidate."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
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


def _runtime_hashes(path: Path) -> dict[str, str]:
    hashes = {}
    for line in path.read_text(encoding="ascii").splitlines():
        digest, filename = line.split("  ", 1)
        hashes[filename] = digest
    return hashes


def _copy_runtime_wheels(
    source: Path,
    destination: Path,
    requirements: dict[str, str],
    hashes: dict[str, str],
) -> None:
    if not source.is_dir():
        raise RuntimeError("runtime wheelhouse does not exist")
    copied: list[tuple[str, str]] = []
    for wheel in source.glob("*.whl"):
        identity = _wheel_identity(wheel)
        if identity is not None and identity in requirements.items():
            digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
            if hashes.get(wheel.name) != digest:
                raise RuntimeError(f"runtime wheel hash mismatch: {wheel.name}")
            shutil.copy2(wheel, destination / wheel.name)
            copied.append(identity)
    if len(copied) != len(set(copied)) or set(copied) != set(requirements.items()):
        raise RuntimeError("runtime wheelhouse does not exactly satisfy the lock")
    if {item.name for item in destination.glob("*.whl")} != set(hashes):
        raise RuntimeError("runtime wheel filenames do not exactly satisfy the hash lock")


def _source_ignore(_directory: str, names: list[str]) -> set[str]:
    """Exclude local build, cache, and temporary artifacts from the source copy."""
    excluded = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
        "tmp",
        ".tmp",
        "__pycache__",
    }
    return {name for name in names if name in excluded or name.endswith(".pyc")}


def _build_project_wheel(root: Path, wheelhouse: Path, environment: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="mcpserver-source-") as temporary:
        source = Path(temporary) / "source"
        shutil.copytree(
            root,
            source,
            ignore=_source_ignore,
        )
        text_suffixes = {".py", ".md", ".toml", ".yaml", ".yml", ".txt"}
        for path in source.rglob("*"):
            if path.is_file() and (path.suffix.lower() in text_suffixes or path.name == "LICENSE"):
                path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
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
            root=source,
            environment=environment,
        )
    wheel = next(wheelhouse.glob("loxberry_mcpserver-*.whl"))
    canonical = wheel.with_suffix(".canonical.whl")
    with zipfile.ZipFile(wheel) as source_archive, zipfile.ZipFile(canonical, "w") as output:
        for name in sorted(source_archive.namelist()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            output.writestr(info, source_archive.read(name))
    canonical.replace(wheel)


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
    parser.add_argument(
        "--official",
        action="store_true",
        help="Create the official filename; accepted only on GitHub Actions master.",
    )
    parser.add_argument("--skip-tests", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.official and not (
        os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REF_NAME") == "master"
    ):
        raise RuntimeError("official packages may only be built by GitHub Actions on master")
    environment = {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONPATH": str(root / "src"),
        "SOURCE_DATE_EPOCH": "1767225600",
    }

    if not args.skip_tests:
        with tempfile.TemporaryDirectory(prefix="mcpserver-tests-", dir=output_dir) as test_temp:
            test_environment = {
                **environment,
                "PYTEST_ADDOPTS": shlex.join(
                    [f"--basetemp={Path(test_temp).as_posix()}", "-p", "no:cacheprovider"]
                ),
            }
            _run(sys.executable, "tools/test.py", root=root, environment=test_environment)
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
            hashes = _runtime_hashes(root / "requirements" / "runtime-arm64.sha256")
            _copy_runtime_wheels(
                args.runtime_wheelhouse.resolve(), wheelhouse, requirements, hashes
            )
            _build_project_wheel(root, wheelhouse, environment)

        candidate = work / "candidate.zip"
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
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()

        if args.official:
            filename = f"LoxBerry-MCP-Server-{_version(root)}.zip"
        else:
            commit = subprocess.run(
                ["git", "rev-parse", "--short=7", "HEAD"],
                check=True,
                cwd=root,
                capture_output=True,
                text=True,
            ).stdout.strip()
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    check=True,
                    cwd=root,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            filename = (
                f"LoxBerry-MCP-Server-{_version(root)}-local-{commit}"
                f"{'-dirty' if dirty else ''}.zip"
            )
        output = output_dir / filename
        _publish(candidate, output, digest)
        _run(
            sys.executable,
            "tools/verify_plugin.py",
            str(output),
            root=root,
            environment=environment,
        )

    print(f"RELEASE_CANDIDATE=pass path={output}")
    print(f"SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
