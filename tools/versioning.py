"""Shared release-version contract helpers."""

from __future__ import annotations

import re

VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta)\.(?:0|[1-9][0-9]*))?$")


def project_version(version: str) -> str:
    """Convert project prerelease labels to their PEP 440 wheel form."""
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("version must use x.y.z, x.y.z-alpha.n or x.y.z-beta.n")
    return re.sub(
        r"-(alpha|beta)\.([0-9]+)$",
        lambda match: {"alpha": "a", "beta": "b"}[match.group(1).lower()] + match.group(2),
        version,
    )
