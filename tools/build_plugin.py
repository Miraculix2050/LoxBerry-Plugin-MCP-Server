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
    "webfrontend/htmlauth/explorer.cgi",
    "webfrontend/htmlauth/explorer_callback.cgi",
}
_TEXT_SUFFIXES: Final = {
    ".cfg",
    ".cgi",
    ".conf",
    ".html",
    ".ini",
    ".json",
    ".js",
    ".lock",
    ".md",
    ".sh",
    ".svg",
    ".txt",
}
_TEXT_NAMES: Final = {".gitattributes", "LICENSE", "bin/healthcheck", "bin/mcpserver-admin"}


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


def _wheel_identities(wheelhouse: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for item in wheelhouse.glob("*.whl"):
        parts = item.name.removesuffix(".whl").split("-")
        if len(parts) >= 5:
            result.append((re.sub(r"[-_.]+", "-", parts[0]).lower(), parts[1].lower()))
    return result


def _verify_project_wheel(project_wheel: Path, source_root: Path) -> None:
    try:
        wheel = zipfile.ZipFile(project_wheel)
    except zipfile.BadZipFile as exc:
        raise SystemExit("project wheel is not a valid wheel archive") from exc
    with wheel:
        sources = {
            source.relative_to(source_root).as_posix(): source
            for source in (source_root / "mcpserver").rglob("*.py")
        }
        members = [
            name
            for name in wheel.namelist()
            if name.startswith("mcpserver/") and name.endswith(".py")
        ]
        if len(members) != len(set(members)) or set(members) != set(sources):
            raise SystemExit("project wheel Python source set differs from current source")
        for name, source in sources.items():
            try:
                packaged = wheel.read(name)
            except KeyError as exc:
                raise SystemExit(f"project wheel is missing current source: {name}") from exc
            if packaged != source.read_bytes():
                raise SystemExit(f"project wheel contains stale source: {name}")


def _add(archive: zipfile.ZipFile, source: Path, target: str) -> None:
    info = zipfile.ZipInfo(target.replace("\\", "/"), _TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    mode = 0o755 if target.replace("\\", "/") in _EXECUTABLES else 0o644
    info.external_attr = (mode | 0o100000) << 16
    content = source.read_bytes()
    target_path = Path(target)
    if target_path.suffix.lower() in _TEXT_SUFFIXES or target.replace("\\", "/") in _TEXT_NAMES:
        content = content.replace(b"\r\n", b"\n")
    archive.writestr(info, content)


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
    wheel_files = list(wheelhouse.glob("*.whl"))
    wheel_identities = _wheel_identities(wheelhouse)
    wheel_versions = set(wheel_identities)
    project_identities = [
        identity for identity in wheel_identities if identity[0] == "loxberry-mcpserver"
    ]
    runtime_wheels = [
        identity for identity in wheel_identities if identity[0] != "loxberry-mcpserver"
    ]
    expected_runtime = {(name, version.lower()) for name, version in requirements.items()}
    missing = set(requirements) - _wheel_names(wheelhouse)
    mismatched = {
        name
        for name, version in requirements.items()
        if (name, version.lower()) not in wheel_versions
    }
    project_wheels = tuple(wheelhouse.glob("loxberry_mcpserver-0.2.0a1-*.whl"))
    expected_project = [("loxberry-mcpserver", "0.2.0a1")]
    unexpected = set(runtime_wheels) - expected_runtime
    duplicates = len(runtime_wheels) != len(set(runtime_wheels))
    invalid_wheel = len(wheel_files) != len(wheel_identities)
    if (
        missing
        or mismatched
        or unexpected
        or duplicates
        or invalid_wheel
        or len(project_wheels) != 1
        or project_identities != expected_project
    ):
        detail = ", ".join(sorted(missing | mismatched)) or "project wheel"
        if unexpected:
            detail = ", ".join(sorted(name for name, _version in unexpected))
        if duplicates:
            detail = "duplicate runtime wheel"
        if invalid_wheel:
            detail = "invalid wheel filename"
        if project_identities != expected_project:
            detail = "unexpected project wheel"
        raise SystemExit(f"wheelhouse is incomplete: {detail}")

    _verify_project_wheel(project_wheels[0], root / "src")

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
