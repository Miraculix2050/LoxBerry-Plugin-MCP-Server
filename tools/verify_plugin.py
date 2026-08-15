"""Verify a built LoxBerry plugin archive without extracting it."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Final

try:
    from tools.build_plugin import _TIMESTAMP, expected_source_entries
    from tools.versioning import project_version
except ModuleNotFoundError:  # Direct documented CLI execution from repository root.
    from build_plugin import _TIMESTAMP, expected_source_entries
    from versioning import project_version

_REQUIRED: Final = {
    "plugin.cfg",
    "preinstall.sh",
    "preupgrade.sh",
    "postinstall.sh",
    "postroot.sh",
    "postupgrade.sh",
    "uninstall/uninstall.sh",
    "bin/healthcheck",
    "bin/mcpserver-admin",
    "bin/renew-web-certificate",
    "bin/runtime-arm64.lock",
    "config/default-config.json",
    "config/apache/mcpserver.conf",
    "config/systemd/loxberry-mcpserver.service.in",
    "webfrontend/htmlauth/index.cgi",
    "webfrontend/htmlauth/explorer.cgi",
    "webfrontend/htmlauth/explorer_callback.cgi",
    "webfrontend/htmlauth/explorer.js",
    "templates/index.html",
    "templates/explorer.html",
    "templates/lang/language_de.ini",
    "templates/lang/language_en.ini",
}
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
    ".html",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".sh",
    ".svg",
}
_TEXT_NAMES: Final = {"bin/healthcheck", "bin/mcpserver-admin", "bin/renew-web-certificate"}
_REQUIRED_PROJECT_WHEEL_ENTRIES: Final = {
    "mcpserver/skills/using-loxberry-mcp/SKILL.md",
    "mcpserver/skills/using-loxberry-mcp/agents/openai.yaml",
}


class PackageVerificationError(RuntimeError):
    """The archive violates the Phase 1 package contract."""


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _locked_requirements(content: str) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in content.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", line)
        if match:
            requirements[_normalized_name(match.group(1))] = match.group(2).lower()
    return requirements


def _wheel_identity(filename: str) -> tuple[str, str] | None:
    parts = PurePosixPath(filename).name.removesuffix(".whl").split("-")
    if len(parts) < 5:
        return None
    return _normalized_name(parts[0]), parts[1].lower()


def _expected_project_version(plugin_version: str) -> str:
    return project_version(plugin_version)


def _verify_checksum(archive: Path, digest: str) -> None:
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if not sidecar.exists():
        raise PackageVerificationError("checksum sidecar is missing")
    fields = sidecar.read_text(encoding="ascii").strip().split()
    if fields != [digest, archive.name]:
        raise PackageVerificationError("checksum sidecar does not match the archive")


def _verify_project_wheel(content: bytes, source_root: Path) -> None:
    try:
        wheel = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise PackageVerificationError("project wheel is not a valid wheel archive") from exc
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
            raise PackageVerificationError(
                "project wheel Python source set differs from current source"
            )
        for name, source in sources.items():
            try:
                packaged = wheel.read(name)
            except KeyError as exc:
                raise PackageVerificationError(
                    f"project wheel is missing current source: {name}"
                ) from exc
            if packaged.replace(b"\r\n", b"\n") != source.read_bytes().replace(b"\r\n", b"\n"):
                raise PackageVerificationError(f"project wheel contains stale source: {name}")
        missing = _REQUIRED_PROJECT_WHEEL_ENTRIES - set(wheel.namelist())
        if missing:
            raise PackageVerificationError(
                f"required project wheel entry is missing: {min(missing)}"
            )


def verify_archive(archive: Path, *, require_checksum: bool = True) -> str:
    """Validate layout, modes, LF text files, identity, wheels, and checksum."""
    archive = archive.resolve()
    if not archive.is_file():
        raise PackageVerificationError("plugin archive does not exist")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if require_checksum:
        _verify_checksum(archive, digest)

    try:
        package = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise PackageVerificationError("plugin archive is not a valid ZIP") from exc

    with package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise PackageVerificationError("plugin archive contains duplicate paths")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (
                entry.is_dir()
                or entry.filename.startswith("/")
                or "\\" in entry.filename
                or ".." in path.parts
                or not path.parts
            ):
                raise PackageVerificationError("plugin archive contains an unsafe path")
            mode = entry.external_attr >> 16
            if not stat.S_ISREG(mode):
                raise PackageVerificationError("plugin archive contains a non-regular file")
            expected_mode = 0o755 if entry.filename in _EXECUTABLES else 0o644
            if stat.S_IMODE(mode) != expected_mode:
                raise PackageVerificationError(f"unexpected file mode for {entry.filename}")
            if entry.date_time != _TIMESTAMP or entry.compress_type != zipfile.ZIP_STORED:
                raise PackageVerificationError(f"non-canonical ZIP metadata for {entry.filename}")
            if (
                path.suffix.lower() in _TEXT_SUFFIXES or entry.filename in _TEXT_NAMES
            ) and b"\r\n" in package.read(entry):
                raise PackageVerificationError(f"CRLF found in {entry.filename}")

        missing = _REQUIRED - set(names)
        if missing:
            raise PackageVerificationError(f"required package entry is missing: {min(missing)}")

        parser = configparser.ConfigParser()
        parser.read_file(io.StringIO(package.read("plugin.cfg").decode("utf-8")))
        if (
            parser["PLUGIN"].get("NAME") != "mcpserver"
            or parser["PLUGIN"].get("FOLDER") != "mcpserver"
        ):
            raise PackageVerificationError("plugin identity is invalid")
        version = parser["PLUGIN"].get("VERSION", "")
        expected_project = ("loxberry-mcpserver", _expected_project_version(version).lower())
        wheelhouse_entries = [name for name in names if name.startswith("bin/wheelhouse/")]
        expected_names = expected_source_entries(Path(__file__).resolve().parents[1]) | set(
            wheelhouse_entries
        )
        if set(names) != expected_names:
            extra = set(names) - expected_names
            missing_exact = expected_names - set(names)
            detail = min(extra or missing_exact)
            raise PackageVerificationError(f"plugin archive violates exact manifest: {detail}")
        if any(
            PurePosixPath(name).parent != PurePosixPath("bin/wheelhouse")
            or PurePosixPath(name).suffix != ".whl"
            or _wheel_identity(name) is None
            for name in wheelhouse_entries
        ):
            raise PackageVerificationError("wheelhouse contains an invalid entry")
        wheel_identities = [_wheel_identity(name) for name in wheelhouse_entries]
        project_wheel_entries = [
            name
            for name, identity in zip(wheelhouse_entries, wheel_identities, strict=True)
            if identity is not None and identity[0] == "loxberry-mcpserver"
        ]
        project_wheels = [
            identity
            for identity in wheel_identities
            if identity is not None and identity[0] == "loxberry-mcpserver"
        ]
        if project_wheels != [expected_project] or len(project_wheel_entries) != 1:
            raise PackageVerificationError("exactly one matching project wheel is required")
        _verify_project_wheel(
            package.read(project_wheel_entries[0]),
            Path(__file__).resolve().parents[1] / "src",
        )
        expected_runtime = _locked_requirements(
            package.read("bin/runtime-arm64.lock").decode("utf-8")
        )
        runtime_wheels = [
            identity
            for identity in wheel_identities
            if identity is not None and identity[0] != "loxberry-mcpserver"
        ]
        if len(runtime_wheels) != len(set(runtime_wheels)):
            raise PackageVerificationError("offline runtime wheelhouse contains duplicates")
        if set(runtime_wheels) != set(expected_runtime.items()):
            raise PackageVerificationError("offline runtime wheelhouse does not match its lock")
        locked_hashes = {}
        for line in package.read("bin/runtime-arm64.sha256").decode("ascii").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.+-]+\.whl)", line)
            if match is None:
                raise PackageVerificationError("runtime wheel hash lock is invalid")
            locked_hashes[match.group(2)] = match.group(1)
        actual_hashes = {
            PurePosixPath(name).name: hashlib.sha256(package.read(name)).hexdigest()
            for name, identity in zip(wheelhouse_entries, wheel_identities, strict=True)
            if identity is not None and identity[0] != "loxberry-mcpserver"
        }
        if actual_hashes != locked_hashes:
            raise PackageVerificationError("runtime wheel hash lock mismatch")

    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--no-checksum", action="store_true")
    args = parser.parse_args()
    digest = verify_archive(args.archive, require_checksum=not args.no_checksum)
    print(f"PLUGIN_ARCHIVE=pass sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
