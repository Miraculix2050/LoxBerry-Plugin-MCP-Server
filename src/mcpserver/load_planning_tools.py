"""Thin read-only MCP adapter for conditional future load planning."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcpserver.context_planning import ContextPlanningResult, calculate_context_plan
from mcpserver.history_analysis import HistoryAnalysisDeadline
from mcpserver.installation_profile import ProfileError
from mcpserver.load_planning import LoadPlanningOptions, LoadPlanningResult
from mcpserver.load_planning_runtime import calculate_load_plan
from mcpserver.loxone.event_history import EventHistoryQueryTimeout, EventHistoryUnavailable
from mcpserver.loxone.runtime import (
    ControlOperationError,
    LoxoneRuntime,
    RuntimeAuthorizationError,
    RuntimeUnavailable,
)
from mcpserver.tools import (
    ErrorData,
    EventHistoryRuntime,
    ToolEnvelope,
    _access,
    _availability_error,
    _error,
    _operation_error,
    _result,
)


class LoadPlanningEnvelope(ToolEnvelope):
    data: LoadPlanningResult | ContextPlanningResult | ErrorData


def register_load_planning_tool(
    server: FastMCP,
    runtime: LoxoneRuntime | None,
    event_runtime: EventHistoryRuntime | None,
    profile_path: Path | None,
    *,
    pending: set[asyncio.Task[Any]] | None = None,
) -> None:
    pending = pending if pending is not None else set()

    async def calculate(options: LoadPlanningOptions) -> LoadPlanningEnvelope:
        try:
            if runtime is None or (profile_path is None and options.analysis_context is None):
                raise RuntimeUnavailable("Load planning is not configured")
            async with asyncio.timeout(30):
                result: LoadPlanningResult | ContextPlanningResult
                if options.analysis_context is not None:
                    result = await calculate_context_plan(
                        runtime,
                        event_runtime,
                        profile_path,
                        _access(),
                        options,
                        deadline=time.monotonic() + 30,
                    )
                else:
                    assert profile_path is not None
                    result = await calculate_load_plan(
                        runtime,
                        event_runtime,
                        profile_path,
                        _access(),
                        options,
                        deadline=time.monotonic() + 30,
                    )
            envelope = _result(LoadPlanningEnvelope, result)
            if len(envelope.model_dump_json().encode()) > 65_536:
                return _error(
                    LoadPlanningEnvelope, "response_too_large", "Planning output exceeds 64 KiB"
                )
            return envelope
        except (HistoryAnalysisDeadline, TimeoutError, EventHistoryQueryTimeout):
            return _error(
                LoadPlanningEnvelope, "temporarily_unavailable", "Planning budget exhausted"
            )
        except ControlOperationError as exc:
            return _operation_error(LoadPlanningEnvelope, exc)
        except (PermissionError, RuntimeAuthorizationError):
            return _error(
                LoadPlanningEnvelope, "permission_denied", "Planning access is not available"
            )
        except RuntimeUnavailable as exc:
            return _availability_error(LoadPlanningEnvelope, exc)
        except (EventHistoryUnavailable, OSError):
            return _error(
                LoadPlanningEnvelope, "temporarily_unavailable", "Planning source unavailable"
            )
        except ProfileError:
            return _error(
                LoadPlanningEnvelope, "temporarily_unavailable", "Planning profile is unavailable"
            )
        except ValueError:
            return _error(
                LoadPlanningEnvelope, "invalid_input", "Invalid planning inputs or source model"
            )

    @server.tool(
        name="loxone_plan_loads",
        description=(
            "Suggest conditional future windows for confirmed flexible consumer bindings using "
            "native PVPF forecasts and explicit baseload/storage scenarios. Legacy profile "
            "selection or analysis_context with one supply budget, up to four disjoint PVPFs, "
            "real declared-cycle loads and explicit hypothetical loads. Read-only; requires "
            "loxone:read and activated loxone:history for observed cycle models. At most 16 loads "
            "and 72 hours. Unknown native constraints remain conditions, not operating permission. "
            "See energy guidance."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
        structured_output=True,
    )
    async def planning(options: LoadPlanningOptions) -> LoadPlanningEnvelope:
        if len(pending) >= 2:
            return _error(
                LoadPlanningEnvelope, "temporarily_unavailable", "Two plans are already running"
            )
        task = asyncio.create_task(calculate(options))
        pending.add(task)
        task.add_done_callback(pending.discard)
        return await asyncio.shield(task)
