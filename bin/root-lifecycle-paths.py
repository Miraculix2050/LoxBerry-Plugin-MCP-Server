#!/usr/bin/python3
"""Prepare plugin-owned paths without following attacker-controlled links."""

from __future__ import annotations

import argparse
import contextlib
import grp
import os
import pwd
import re
import stat
from collections.abc import Sequence

DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
PLUGIN_FOLDER_PATTERN = re.compile(r"[A-Za-z0-9_-]+\Z")


def _open_directory_chain(
    home: str, parts: Sequence[str]
) -> tuple[int, list[tuple[str, os.stat_result]]]:
    fd = os.open(home, DIRECTORY_FLAGS)
    paths = [(home, os.fstat(fd))]
    current = home
    try:
        for part in parts:
            next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            current = os.path.join(current, part)
            paths.append((current, os.fstat(fd)))
        return fd, paths
    except BaseException:
        os.close(fd)
        raise


def _verify_directories(paths: Sequence[tuple[str, os.stat_result]]) -> None:
    for path, opened in paths:
        current = os.lstat(path)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
            opened.st_dev,
            opened.st_ino,
        ):
            raise RuntimeError("plugin directory path changed during root operation")


def _identity() -> tuple[int, int]:
    return pwd.getpwnam("loxberry").pw_uid, grp.getgrnam("loxberry").gr_gid


def _validate_inputs(home: str, folder: str) -> None:
    if not os.path.isabs(home) or not PLUGIN_FOLDER_PATTERN.fullmatch(folder):
        raise RuntimeError("invalid lifecycle path input")


def prepare_private_directory(
    home: str,
    folder: str,
    name: str,
    *,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> None:
    """Create a private directory below data/plugins/<folder>."""
    _validate_inputs(home, folder)
    if name != "statistics-cache":
        raise RuntimeError("unsupported private directory")
    if owner_uid is None or owner_gid is None:
        owner_uid, owner_gid = _identity()
    plugin_fd, plugin_paths = _open_directory_chain(home, ("data", "plugins", folder))
    child_fd: int | None = None
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o700, dir_fd=plugin_fd)
        child_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=plugin_fd)
        opened = os.fstat(child_fd)
        if not stat.S_ISDIR(opened.st_mode):
            raise RuntimeError("private path is not a directory")
        os.fchown(child_fd, owner_uid, owner_gid)
        os.fchmod(child_fd, 0o700)
        child_path = os.path.join(home, "data", "plugins", folder, name)
        _verify_directories((*plugin_paths, (child_path, opened)))
    finally:
        if child_fd is not None:
            os.close(child_fd)
        os.close(plugin_fd)


def prepare_install_key(
    home: str,
    folder: str,
    *,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
    root_uid: int = 0,
) -> None:
    """Create or validate the shared installation key and restore root ownership."""
    _validate_inputs(home, folder)
    if owner_uid is None or owner_gid is None:
        owner_uid, owner_gid = _identity()
    plugin_fd, plugin_paths = _open_directory_chain(home, ("data", "plugins", folder))
    auth_fd: int | None = None
    key_fd: int | None = None
    created = False
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir("auth", 0o700, dir_fd=plugin_fd)
        auth_fd = os.open("auth", DIRECTORY_FLAGS, dir_fd=plugin_fd)
        auth_opened = os.fstat(auth_fd)
        os.fchown(auth_fd, owner_uid, owner_gid)
        os.fchmod(auth_fd, 0o700)
        try:
            key_fd = os.open(
                "install.key",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o640,
                dir_fd=auth_fd,
            )
            created = True
            if os.write(key_fd, os.urandom(32)) != 32:
                raise RuntimeError("could not write the installation key")
            os.fsync(key_fd)
        except FileExistsError:
            key_fd = os.open(
                "install.key", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=auth_fd
            )
            existing = os.fstat(key_fd)
            if (
                not stat.S_ISREG(existing.st_mode)
                or existing.st_nlink != 1
                or existing.st_uid not in {0, owner_uid}
                or existing.st_gid != owner_gid
                or stat.S_IMODE(existing.st_mode) not in {0o600, 0o640}
                or len(os.read(key_fd, 33)) != 32
            ):
                raise RuntimeError("existing installation key is unsafe") from None
        os.fchown(key_fd, root_uid, owner_gid)
        os.fchmod(key_fd, 0o640)
        auth_path = os.path.join(home, "data", "plugins", folder, "auth")
        _verify_directories((*plugin_paths, (auth_path, auth_opened)))
    except BaseException:
        if created and auth_fd is not None:
            os.unlink("install.key", dir_fd=auth_fd)
        raise
    finally:
        if key_fd is not None:
            os.close(key_fd)
        if auth_fd is not None:
            os.close(auth_fd)
        os.close(plugin_fd)


def prepare_service_log(
    home: str,
    folder: str,
    *,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> None:
    """Create the service log below log/plugins/<folder> without following links."""
    _validate_inputs(home, folder)
    if owner_uid is None or owner_gid is None:
        owner_uid, owner_gid = _identity()
    log_fd, log_paths = _open_directory_chain(home, ("log", "plugins", folder))
    file_fd: int | None = None
    try:
        file_fd = os.open(
            "service.log",
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o640,
            dir_fd=log_fd,
        )
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise RuntimeError("service log is not a safe regular file")
        os.fchown(file_fd, owner_uid, owner_gid)
        os.fchmod(file_fd, 0o640)
        _verify_directories(log_paths)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(log_fd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("statistics-cache", "install-key", "service-log"))
    parser.add_argument("--home", required=True)
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    if args.operation == "statistics-cache":
        prepare_private_directory(args.home, args.folder, "statistics-cache")
    elif args.operation == "install-key":
        prepare_install_key(args.home, args.folder)
    else:
        prepare_service_log(args.home, args.folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
