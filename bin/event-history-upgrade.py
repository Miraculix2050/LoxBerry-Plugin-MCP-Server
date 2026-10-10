#!/usr/bin/env python3
"""Preserve plugin SQLite snapshots across a native upgrade.

The existing executable path remains compatible; event history and KNX metadata
use the same integrity-checked snapshot operations.
"""

import os
import sqlite3
import stat
import sys
from contextlib import closing
from pathlib import Path


def regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def backup(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if not regular_file(source) or destination.exists():
        raise RuntimeError("unsafe SQLite upgrade path")
    target = sqlite3.connect(destination)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as current:
            current.backup(target)
        integrity = target.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("SQLite backup failed integrity check")
    finally:
        target.close()
    os.chmod(destination, 0o600)


def restore(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if not regular_file(source) or destination.exists():
        raise RuntimeError("unsafe SQLite restore path")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as snapshot:
        if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite restore failed integrity check")
    parent = destination.parent
    parent.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(parent.lstat().st_mode):
        raise RuntimeError("unsafe SQLite restore directory")
    os.chmod(source, 0o600)
    if os.rename in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.replace(source, destination.name, dst_dir_fd=directory)
        finally:
            os.close(directory)
    else:
        os.replace(source, destination)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in {"backup", "restore"}:
        raise SystemExit("usage: event-history-upgrade.py backup|restore SOURCE DESTINATION")
    try:
        {"backup": backup, "restore": restore}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
