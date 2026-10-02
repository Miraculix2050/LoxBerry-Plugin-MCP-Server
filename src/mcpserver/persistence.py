"""Directory durability for authoritative atomic filesystem updates."""

from __future__ import annotations

import os
from pathlib import Path


class PersistenceUncertain(Exception):
    """Marker for a visible change whose durability could not be confirmed."""


def fsync_parent_directory(path: Path) -> None:
    """Sync rename/unlink metadata on POSIX; development platforms skip this step."""
    if os.name != "posix":
        return
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
