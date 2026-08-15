"""Shared release-version contract helpers."""

from __future__ import annotations

import re


def project_version(version: str) -> str:
    """Convert project prerelease labels to their PEP 440 wheel form."""
    return re.sub(
        r"(?i)-(alpha|beta)\.(\d+)$",
        lambda match: {"alpha": "a", "beta": "b"}[match.group(1).lower()] + match.group(2),
        version,
    )
