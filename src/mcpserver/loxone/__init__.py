"""Secure, user-scoped Loxone Gen. 1 integration primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcpserver.loxone.endpoint import MiniserverEndpoint

if TYPE_CHECKING:
    from mcpserver.loxone.cache import UserStateCache
    from mcpserver.loxone.client import LoxoneClient
    from mcpserver.loxone.models import LoxoneStructure, StateRecord

__all__ = [
    "LoxoneClient",
    "LoxoneStructure",
    "MiniserverEndpoint",
    "StateRecord",
    "UserStateCache",
]


def __getattr__(name: str) -> Any:
    """Preserve public exports without importing network clients unnecessarily."""
    if name == "LoxoneClient":
        from mcpserver.loxone.client import LoxoneClient

        return LoxoneClient
    if name == "LoxoneStructure":
        from mcpserver.loxone.models import LoxoneStructure

        return LoxoneStructure
    if name == "StateRecord":
        from mcpserver.loxone.models import StateRecord

        return StateRecord
    if name == "UserStateCache":
        from mcpserver.loxone.cache import UserStateCache

        return UserStateCache
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
