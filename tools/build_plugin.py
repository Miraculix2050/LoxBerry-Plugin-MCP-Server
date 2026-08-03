"""Create a deterministic LoxBerry V4 ZIP from a verified offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Final

_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)
_ROOT_FILES: Final = (
    ".gitattributes",
    "LICENSE",
    "plugin.cfg",
    "preinstall.sh",
    "preupgrade.sh",
    "release.cfg",
    "prerelease.cfg",
    "postinstall.sh",
    "postroot.sh",
    "postupgrade.sh",
)
_DIRECTORIES: Final = ("config", "icons", "templates", "uninstall", "webfrontend")
_EXECUTABLES: Final = {
    "preinstall.sh",
    "preupgrade.sh",
    "postinstall.sh",
    "postroot.sh",
    "postupgrade.sh",
    "uninstall/uninstall.sh",
    "bin/healthcheck",
    "bin/mcpserver-admin",
    "webfrontend/htmlauth/index.cgi",
}


def _locked_requirements(lock: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$", line)
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            requirements[name] = match.group(2)
    return requirements


def _wheel_names(wheelhouse: Path) -> set[str]:
    return {
        re.sub(
            r"[-_.]+",
            "-",
            re.split(r"-(?=\d)", item.name, maxsplit=1)[0],
        ).lower()
        for item in wheelhouse.glob("*.whl")
    }


def _wheel_versions(wheelhouse: Path) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for item in wheelhouse.glob("*.whl"):
        parts = item.name.removesuffix(".whl").split("-")
        if len(parts) >= 5:
            result.add((re.sub(r"[-_.]+", "-", parts[0]).lower(), parts[1].lower()))
    return result


def _add(archive: zipfile.ZipFile, source: Path, target: str) -> None:
    info = zipfile.ZipInfo(target.replace("\\", "/"), _TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if target.replace("\\", "/") in _EXECUTABLES else 0o644
    info.external_attr = (mode | 0o100000) << 16
    archive.writestr(info, source.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    wheelhouse = args.wheelhouse.resolve()
    output = args.output.resolve()
    lock = root / "requirements" / "runtime-arm64.lock"

    requirements = _locked_requirements(lock)
    wheel_versions = _wheel_versions(wheelhouse)
    missing = set(requirements) - _wheel_names(wheelhouse)
    mismatched = {
        name
        for name, version in requirements.items()
        if (name, version.lower()) not in wheel_versions
    }
    project_wheels = tuple(wheelhouse.glob("loxberry_mcpserver-0.1.0a1-*.whl"))
    if missing or mismatched or len(project_wheels) != 1:
        detail = ", ".join(sorted(missing | mismatched)) or "project wheel"
        raise SystemExit(f"wheelhouse is incomplete: {detail}")

    entries: list[tuple[Path, str]] = []
    entries.extend((root / name, name) for name in _ROOT_FILES)
    entries.extend(
        (item, item.relative_to(root).as_posix())
        for directory in _DIRECTORIES
        for item in (root / directory).rglob("*")
        if item.is_file()
    )
    entries.extend(
        [
            (root / "bin" / "healthcheck", "bin/healthcheck"),
            (root / "bin" / "mcpserver-admin", "bin/mcpserver-admin"),
            (lock, "bin/runtime-arm64.lock"),
        ]
    )
    entries.extend((item, f"bin/wheelhouse/{item.name}") for item in wheelhouse.glob("*.whl"))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for source, target in sorted(entries, key=lambda item: item[1]):
            _add(archive, source, target)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii", newline="\n"
    )
    print(output)
    print(output.with_suffix(output.suffix + ".sha256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
