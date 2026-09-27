#!/usr/bin/env python3
"""Preserve the stopped recorder's SQLite snapshot across a native upgrade."""

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
        raise RuntimeError("unsafe event history upgrade path")
    target = sqlite3.connect(destination)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as current:
            current.backup(target)
        integrity = target.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError("event history backup failed integrity check")
    finally:
        target.close()
    os.chmod(destination, 0o600)


def restore(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if not regular_file(source) or destination.exists():
        raise RuntimeError("unsafe event history restore path")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as snapshot:
        if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("event history restore failed integrity check")
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    os.replace(source, destination)
    os.chmod(destination, 0o600)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in {"backup", "restore"}:
        raise SystemExit("usage: event-history-upgrade.py backup|restore SOURCE DESTINATION")
    try:
        {"backup": backup, "restore": restore}[sys.argv[1]](Path(sys.argv[2]), Path(sys.argv[3]))
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
