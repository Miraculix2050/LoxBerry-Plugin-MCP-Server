"""Thin read-only MCP projection of locally confirmed installation metadata."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcpserver.installation_profile import (
    ProfileError,
    ProfileStore,
    installation_identity,
    project_profile,
    visible_controls,
)
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeAuthorizationError, RuntimeUnavailable
from mcpserver.tools import ErrorData, ToolEnvelope, _error, _result, _snapshot


class ProfileBindingData(BaseModel):
    binding_id: str
    role: str
    control_uuid: str
    control_name: str
    source_kind: Literal["state", "statistic"]
    state_uuid: str | None = None
    series_id: str | None = None
    measurement_boundary: str | None = None
    declared_direction: str | None = None
    rationale: str = ""
    confirmed: bool = False
    confirmation_origin: str | None = None
    status: Literal["confirmed", "draft", "needs_review", "invalid"]
    fact_origin: Literal["user_declared"] = "user_declared"
    semantic_status: Literal["not_resolved"] = "not_resolved"
    measurement_boundary_origin: Literal["user_declared"] = "user_declared"


class ProfileData(BaseModel):
    status: Literal["available", "installation_changed"]
    revision: int
    bindings: Annotated[list[ProfileBindingData], Field(max_length=100)]
    next_offset: int | None


class ProfileEnvelope(ToolEnvelope):
    data: ProfileData | ErrorData


def register_profile_read_tool(
    server: FastMCP, runtime: LoxoneRuntime | None, path: Path | None
) -> None:
    @server.tool(
        name="loxone_get_installation_profile",
        description=(
            "Read confirmed installation bindings through fresh caller visibility. "
            "User-declared roles do not prove technical semantics. Requires loxone:read."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def get_installation_profile(
        offset: Annotated[int, Field(ge=0, le=256)] = 0,
        limit: Annotated[int, Field(ge=1, le=100)] = 100,
    ) -> ProfileEnvelope:
        try:
            if runtime is None or path is None:
                raise RuntimeUnavailable("Profile storage is not configured")
            _access, snapshot = await _snapshot(runtime, fresh_visibility=True)
            installation = installation_identity(runtime.endpoint.origin, snapshot.structure)
            document = await asyncio.to_thread(ProfileStore(path).read, installation)
            result = project_profile(
                document,
                installation,
                visible_controls(snapshot.structure),
                offset=offset,
                limit=limit,
            )
            return _result(
                ProfileEnvelope,
                result,
                warnings=[
                    "Profile roles and boundaries are user declarations; "
                    "technical semantics must be resolved independently."
                ],
            )
        except RuntimeAuthorizationError:
            return _error(ProfileEnvelope, "permission_denied", "Profile access is not authorized")
        except PermissionError:
            return _error(ProfileEnvelope, "unauthenticated", "Authentication is required")
        except (ProfileError, RuntimeUnavailable, OSError):
            return _error(ProfileEnvelope, "temporarily_unavailable", "Profile data is unavailable")
