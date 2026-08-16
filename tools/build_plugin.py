"""Create a deterministic LoxBerry V4 ZIP from a verified offline wheelhouse."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Final

try:
    from tools.versioning import project_version
except ModuleNotFoundError:  # Direct documented CLI execution from repository root.
    from versioning import project_version

_TIMESTAMP: Final = (2026, 1, 1, 0, 0, 0)
_ROOT_FILES: Final = (
    "LICENSE",
    "plugin.cfg",
    "preinstall.sh",
    "preupgrade.sh",
    "postinstall.sh",
    "postroot.sh",
    "postupgrade.sh",
)
_DIRECTORIES: Final = ("config", "icons", "templates", "uninstall", "webfrontend")
REFERENCE_HTML_PATH: Final = "webfrontend/htmlauth/tool-schema-reference.html"
REFERENCE_JSON_PATH: Final = "webfrontend/htmlauth/tool-schema-reference.json"
_GENERATED_REFERENCE_PATHS: Final = {REFERENCE_HTML_PATH, REFERENCE_JSON_PATH}
_EXECUTABLES: Final = {
    "preinstall.sh",
    "preupgrade.sh",
    "postinstall.sh",
    "postroot.sh",
    "postupgrade.sh",
    "uninstall/uninstall.sh",
    "bin/healthcheck",
    "bin/mcpserver-admin",
    "bin/renew-web-certificate",
    "webfrontend/htmlauth/index.cgi",
    "webfrontend/htmlauth/explorer.cgi",
    "webfrontend/htmlauth/explorer_callback.cgi",
}
_TEXT_SUFFIXES: Final = {
    ".cfg",
    ".cgi",
    ".conf",
    ".css",
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
_TEXT_NAMES: Final = {
    "LICENSE",
    "bin/healthcheck",
    "bin/mcpserver-admin",
    "bin/renew-web-certificate",
}


def _runtime_hashes(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+\.whl)", line)
        if match is None or match.group(2) in hashes:
            raise SystemExit("runtime wheel hash lock is invalid")
        hashes[match.group(2)] = match.group(1)
    if not hashes:
        raise SystemExit("runtime wheel hash lock is empty")
    return hashes


def expected_source_entries(root: Path) -> set[str]:
    """Return the exact non-wheel installable package contract."""
    entries = set(_ROOT_FILES)
    entries.update(
        item.relative_to(root).as_posix()
        for directory in _DIRECTORIES
        for item in (root / directory).rglob("*")
        if item.is_file() and item.relative_to(root).as_posix() not in _GENERATED_REFERENCE_PATHS
    )
    entries.update(
        {
            "bin/healthcheck",
            "bin/mcpserver-admin",
            "bin/renew-web-certificate",
            "bin/runtime-arm64.lock",
            "bin/runtime-arm64.sha256",
            REFERENCE_HTML_PATH,
            REFERENCE_JSON_PATH,
        }
    )
    return entries


def _locked_requirements(lock: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$", line)
        if match:
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            requirements[name] = match.group(2)
    return requirements


def _release_version(root: Path) -> str:
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str):
        raise SystemExit("project version is missing")
    project_version(version)
    return version


def _project_version(root: Path) -> str:
    return project_version(_release_version(root))


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
            if packaged.replace(b"\r\n", b"\n") != source.read_bytes().replace(b"\r\n", b"\n"):
                raise SystemExit(f"project wheel contains stale source: {name}")


def _add_content(archive: zipfile.ZipFile, content: bytes, target: str) -> None:
    info = zipfile.ZipInfo(target.replace("\\", "/"), _TIMESTAMP)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    mode = 0o755 if target.replace("\\", "/") in _EXECUTABLES else 0o644
    info.external_attr = (mode | 0o100000) << 16
    target_path = Path(target)
    if target_path.suffix.lower() in _TEXT_SUFFIXES or target.replace("\\", "/") in _TEXT_NAMES:
        content = content.replace(b"\r\n", b"\n")
    archive.writestr(info, content)


def _add(archive: zipfile.ZipFile, source: Path, target: str) -> None:
    _add_content(archive, source.read_bytes(), target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--runtime-hash-lock",
        type=Path,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from mcpserver.schema_reference import schema_reference_html, schema_reference_json

    wheelhouse = args.wheelhouse.resolve()
    output = args.output.resolve()
    lock = root / "requirements" / "runtime-arm64.lock"
    hash_lock = (
        args.runtime_hash_lock.resolve()
        if args.runtime_hash_lock
        else root / "requirements" / "runtime-arm64.sha256"
    )

    requirements = _locked_requirements(lock)
    runtime_hashes = _runtime_hashes(hash_lock)
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
    actual_runtime_files = {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in wheel_files
        if not item.name.startswith("loxberry_mcpserver-")
    }
    missing = set(requirements) - _wheel_names(wheelhouse)
    mismatched = {
        name
        for name, version in requirements.items()
        if (name, version.lower()) not in wheel_versions
    }
    release_version = _release_version(root)
    project_wheel_version = _project_version(root)
    project_wheels = tuple(wheelhouse.glob(f"loxberry_mcpserver-{project_wheel_version}-*.whl"))
    expected_project = [("loxberry-mcpserver", project_wheel_version.lower())]
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
        or actual_runtime_files != runtime_hashes
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
        if actual_runtime_files != runtime_hashes:
            detail = "runtime wheel hash lock mismatch"
        raise SystemExit(f"wheelhouse is incomplete: {detail}")

    _verify_project_wheel(project_wheels[0], root / "src")

    entries: list[tuple[Path, str]] = []
    entries.extend((root / name, name) for name in _ROOT_FILES)
    entries.extend(
        (item, item.relative_to(root).as_posix())
        for directory in _DIRECTORIES
        for item in (root / directory).rglob("*")
        if item.is_file() and item.relative_to(root).as_posix() not in _GENERATED_REFERENCE_PATHS
    )
    entries.extend(
        [
            (root / "bin" / "healthcheck", "bin/healthcheck"),
            (root / "bin" / "mcpserver-admin", "bin/mcpserver-admin"),
            (root / "bin" / "renew-web-certificate", "bin/renew-web-certificate"),
            (lock, "bin/runtime-arm64.lock"),
            (hash_lock, "bin/runtime-arm64.sha256"),
        ]
    )
    entries.extend((item, f"bin/wheelhouse/{item.name}") for item in wheelhouse.glob("*.whl"))

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for source, target in sorted(entries, key=lambda item: item[1]):
            _add(archive, source, target)
        _add_content(archive, schema_reference_html(release_version), REFERENCE_HTML_PATH)
        _add_content(archive, schema_reference_json(release_version), REFERENCE_JSON_PATH)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest}  {output.name}\n", encoding="ascii", newline="\n"
    )
    print(output)
    print(output.with_suffix(output.suffix + ".sha256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
