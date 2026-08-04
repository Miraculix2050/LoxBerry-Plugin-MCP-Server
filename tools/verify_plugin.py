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

from tools.build_plugin import _EXECUTABLES

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
    "bin/runtime-arm64.lock",
    "config/default-config.json",
    "config/apache/mcpserver.conf",
    "config/systemd/loxberry-mcpserver.service.in",
    "webfrontend/htmlauth/index.cgi",
    "templates/index.html",
    "templates/lang/language_de.ini",
    "templates/lang/language_en.ini",
}
_TEXT_SUFFIXES: Final = {".cfg", ".cgi", ".conf", ".html", ".ini", ".json", ".lock", ".sh", ".svg"}
_TEXT_NAMES: Final = {"bin/healthcheck", "bin/mcpserver-admin"}


class PackageVerificationError(RuntimeError):
    """The archive violates the Phase 1 package contract."""


def _expected_project_version(plugin_version: str) -> str:
    return re.sub(r"(?i)-alpha\.(\d+)$", r"a\1", plugin_version)


def _verify_checksum(archive: Path, digest: str) -> None:
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if not sidecar.exists():
        raise PackageVerificationError("checksum sidecar is missing")
    fields = sidecar.read_text(encoding="ascii").strip().split()
    if fields != [digest, archive.name]:
        raise PackageVerificationError("checksum sidecar does not match the archive")


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
        expected_wheel = f"bin/wheelhouse/loxberry_mcpserver-{_expected_project_version(version)}-"
        project_wheels = [name for name in names if name.startswith(expected_wheel)]
        if len(project_wheels) != 1:
            raise PackageVerificationError("exactly one matching project wheel is required")
        runtime_wheels = [name for name in names if name.startswith("bin/wheelhouse/")]
        if len(runtime_wheels) < 2:
            raise PackageVerificationError("offline runtime wheelhouse is incomplete")

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
