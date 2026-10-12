"""Thin MCP adapters for installation metadata and independently approved writes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcpserver.installation_profile import (
    ProfileBindingInput,
    ProfileError,
    ProfileSources,
    ProfileStore,
    PVParameters,
    WeatherField,
    installation_identity,
    project_profile,
)
from mcpserver.installation_profile_write import ProfileWriteRuntime
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeAuthorizationError, RuntimeUnavailable
from mcpserver.persistence import PersistenceUncertain
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
    semantic_reference: str | None = None
    measurement_boundary_origin: Literal["user_declared"] = "user_declared"
    pv_parameters: PVParameters | None = None
    pv_parameters_usable: bool = False


class WeatherProfileBindingData(BaseModel):
    binding_id: str
    role: Literal["weather_context"]
    source_kind: Literal["weather"]
    weather_state_uuid: str
    mode: Literal["actual", "forecast"]
    field: WeatherField
    rationale: str
    confirmed: bool
    confirmation_origin: str | None
    status: Literal["confirmed", "draft", "needs_review"]
    fact_origin: Literal["user_declared"]
    semantic_status: Literal["not_resolved"]
    semantic_reference: str | None
    source_format: str | None
    unit: None = None
    history_status: Literal["unavailable"]
    value_origin: Literal["current_source_value", "forecast"]


class ProfileData(BaseModel):
    status: Literal["available", "installation_changed"]
    revision: int
    bindings: Annotated[list[ProfileBindingData | WeatherProfileBindingData], Field(max_length=100)]
    next_offset: int | None


class ProfileEnvelope(ToolEnvelope):
    data: ProfileData | ErrorData


class ProfileMutationData(BaseModel):
    revision: int
    binding_id: str | None


class ProfileMutationEnvelope(ToolEnvelope):
    data: ProfileMutationData | ErrorData


def register_profile_write_tools(server: FastMCP, runtime: ProfileWriteRuntime | None) -> None:
    from mcpserver.tools import _access

    async def change(
        revision: int, confirm: bool, binding: ProfileBindingInput | None, binding_id: str | None
    ) -> ProfileMutationEnvelope:
        access = None
        tool = (
            "loxberry_save_installation_profile"
            if binding is not None
            else "loxberry_delete_installation_profile"
        )
        outcome = "failed"
        try:
            access = _access()
            if confirm is not True:
                raise ProfileError("confirmation_required")
            if runtime is None:
                raise RuntimeUnavailable("Profile management is not configured")
            result = await runtime.change(access, revision, binding=binding, binding_id=binding_id)
            outcome = "completed"
            return _result(ProfileMutationEnvelope, result)
        except (RuntimeAuthorizationError, PermissionError):
            outcome = "permission_denied"
            return _error(ProfileMutationEnvelope, outcome, "Profile management is not authorized")
        except ProfileError as exc:
            outcome = exc.code
            return _error(ProfileMutationEnvelope, outcome, "Profile operation rejected")
        except (TimeoutError, PersistenceUncertain):
            outcome = "write_outcome_uncertain"
            return _error(
                ProfileMutationEnvelope,
                outcome,
                "Inspect the profile before another write; do not automatically retry",
            )
        except asyncio.CancelledError:
            outcome = "write_outcome_uncertain"
            raise
        except (RuntimeUnavailable, OSError, ValueError):
            outcome = "temporarily_unavailable"
            return _error(ProfileMutationEnvelope, outcome, "Profile management is unavailable")
        finally:
            if runtime is not None:
                runtime.audit(access, tool, outcome)

    @server.tool(
        name="loxberry_save_installation_profile",
        description=(
            "Save one exact profile binding after explicit user confirmation in chat. "
            "Requires loxone:read, loxberry:operate and an independent exact local profile "
            "approval. The existing operate scope also requires loxone:history. "
            "Never retry an uncertain write."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
        structured_output=True,
    )
    async def save_installation_profile(
        binding: ProfileBindingInput,
        expected_revision: Annotated[int, Field(strict=True, ge=0, lt=2**31 - 1)],
        confirm: Annotated[bool, Field(strict=True)] = False,
    ) -> ProfileMutationEnvelope:
        return await change(expected_revision, confirm, binding, None)

    @server.tool(
        name="loxberry_delete_installation_profile",
        description=(
            "Delete one profile binding, or the entire profile only if all affected bindings "
            "are currently visible. Requires explicit user confirmation in chat, loxone:read, "
            "loxberry:operate and an independent exact local profile approval. The existing "
            "operate scope also requires loxone:history. Never retry an uncertain write."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
        ),
        structured_output=True,
    )
    async def delete_installation_profile(
        expected_revision: Annotated[int, Field(strict=True, ge=0, lt=2**31 - 1)],
        binding_id: Annotated[str | None, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = None,
        confirm: Annotated[bool, Field(strict=True)] = False,
    ) -> ProfileMutationEnvelope:
        return await change(expected_revision, confirm, None, binding_id)


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
            access, snapshot = await _snapshot(runtime, fresh_visibility=True)
            installation = installation_identity(runtime.endpoint.origin, snapshot.structure)
            document = await asyncio.to_thread(ProfileStore(path).read, installation)
            # File locking can yield long enough for revocation or expiry. This
            # rechecks caller OAuth policy, without another Miniserver probe.
            await runtime._require_access(access)
            result = project_profile(
                document,
                installation,
                ProfileSources.from_structure(installation, snapshot.structure),
                offset=offset,
                limit=limit,
            )
            envelope = _result(
                ProfileEnvelope,
                result,
                warnings=[
                    "Profile roles and boundaries are user declarations; "
                    "technical semantics must be resolved independently."
                ],
            )
            if len(json.dumps(envelope.model_dump(), ensure_ascii=False).encode("utf-8")) > 65536:
                return _error(
                    ProfileEnvelope, "response_too_large", "Request a smaller profile page"
                )
            return envelope
        except RuntimeAuthorizationError:
            return _error(ProfileEnvelope, "permission_denied", "Profile access is not authorized")
        except PermissionError:
            return _error(ProfileEnvelope, "unauthenticated", "Authentication is required")
        except (ProfileError, RuntimeUnavailable, OSError):
            return _error(ProfileEnvelope, "temporarily_unavailable", "Profile data is unavailable")
