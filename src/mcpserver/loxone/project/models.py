"""Immutable project data and shared resource limits."""

from dataclasses import dataclass, field


class ProjectError(RuntimeError):
    """A fixed diagnostic category, never a source value or exception message."""


@dataclass(frozen=True, slots=True)
class ProjectLimits:
    download_bytes: int = 8 * 1024 * 1024
    archive_entries: int = 32
    expanded_bytes: int = 64 * 1024 * 1024
    decoded_bytes: int = 64 * 1024 * 1024
    timeout_seconds: float = 20.0
    elements: int = 200_000
    attributes: int = 1_000_000
    depth: int = 128
    edges: int = 400_000


@dataclass(frozen=True, slots=True)
class ProjectFile:
    key: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProjectBundle:
    fingerprint: str
    files: tuple[ProjectFile, ...] = field(repr=False)
    byte_count: int


DEFAULT_LIMITS = ProjectLimits()
