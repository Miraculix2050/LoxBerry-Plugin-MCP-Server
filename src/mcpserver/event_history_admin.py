"""Narrow local Admin use cases for the plugin-owned event history."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from mcpserver.config import PluginConfig
from mcpserver.emergency_stop import EmergencyStopMonitor
from mcpserver.loxone.event_history import EventHistoryMonitor, EventHistoryStore
from mcpserver.loxone.uuid import normalize_loxone_uuid

_DISCOVERY_TIMEOUT = 35
_SOURCE_LIMIT = 64


def _bridge() -> Any:
    from mcpserver import admin

    return admin


def _store(config: PluginConfig) -> EventHistoryStore:
    bridge = _bridge()
    path = Path(os.getenv("MCPSERVER_EVENT_HISTORY_STORE", ""))
    if not path.is_absolute() or path.suffix != ".sqlite3":
        raise bridge.AdminError(
            "local event history is unavailable", code="temporarily_unavailable"
        )
    return EventHistoryStore(
        path,
        retention_days=config.event_history_retention_days,
        maximum_mib=config.event_history_maximum_mib,
    )


def _monitor(config: PluginConfig) -> EventHistoryMonitor:
    return EventHistoryMonitor(config, _store(config), EmergencyStopMonitor(config))


def _controls(config: PluginConfig) -> tuple[Any, ...]:
    bridge = _bridge()
    if not config.loxone_endpoint:
        raise bridge.AdminError("Miniserver is not configured", code="temporarily_unavailable")
    try:
        return asyncio.run(
            asyncio.wait_for(_monitor(config).visible_controls(), timeout=_DISCOVERY_TIMEOUT)
        )
    except (TimeoutError, OSError, RuntimeError, ValueError) as exc:
        raise bridge.AdminError(
            "visible Miniserver structure is unavailable", code="temporarily_unavailable"
        ) from exc


def _visible(controls: tuple[Any, ...]) -> dict[tuple[str, str], tuple[str, str, str]]:
    return {
        (control.uuid, state_uuid): (control.name, control.control_type, state_name)
        for control in controls
        if control.control_type != "Daytimer"
        for state_name, state_uuid in control.state_uuids
    }


def _source(payload: object) -> tuple[str, str]:
    bridge = _bridge()
    if not isinstance(payload, dict):
        raise bridge.AdminError("source is invalid")
    try:
        control = normalize_loxone_uuid(payload.get("control_uuid"))
        state = normalize_loxone_uuid(payload.get("state_uuid"))
    except (TypeError, ValueError) as exc:
        raise bridge.AdminError("source is invalid") from exc
    return control, state


def _confirmed(payload: object) -> None:
    bridge = _bridge()
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise bridge.AdminError("explicit confirmation is required", code="confirmation_required")


def _require_same_visibility_context(checked: PluginConfig, current: PluginConfig) -> None:
    """Reject a write if discovery no longer describes the configured Miniserver."""
    if (checked.loxone_endpoint, checked.connection_timeout) != (
        current.loxone_endpoint,
        current.connection_timeout,
    ):
        raise _bridge().AdminError(
            "Miniserver configuration changed; search again", code="stale_configuration"
        )


def _apply(change: Callable[[PluginConfig], PluginConfig]) -> tuple[PluginConfig, bool]:
    """Persist one field-limited change and restore the previous running config on failure."""
    bridge = _bridge()
    changed = False

    def transaction(previous: PluginConfig, save: Any) -> PluginConfig:
        nonlocal changed
        updated = change(previous)
        if updated == previous:
            return previous
        active = bridge._service_active()
        save(updated)
        if active:
            try:
                bridge._restart_service()
            except bridge.AdminError as exc:
                try:
                    save(previous)
                    bridge._restart_service()
                except bridge.AdminError as rollback_error:
                    raise bridge.AdminError(
                        "event history apply and rollback failed", code="outcome_unknown"
                    ) from rollback_error
                raise bridge.AdminError(
                    "event history was not applied; previous configuration restored",
                    code="apply_failed",
                ) from exc
        changed = True
        return updated

    result = bridge._config_store().transaction(transaction)
    return cast(PluginConfig, result), changed


def overview() -> dict[str, Any]:
    bridge = _bridge()
    config = bridge._config_store().load()
    store = _store(config)
    response: dict[str, Any] = {
        "enabled": config.event_history_enabled,
        "retention_days": config.event_history_retention_days,
        "maximum_mib": config.event_history_maximum_mib,
        "active_source_count": len(config.event_history_sources),
        "measured_at": time.time(),
        "store_status": "unavailable",
        "visibility_status": "unavailable",
        "sources": [],
    }
    try:
        snapshot = store.snapshot(config.event_history_sources)
        response.update(
            measured_at=snapshot.measured_at,
            database_bytes=snapshot.database_bytes,
            wal_bytes=snapshot.wal_bytes,
            store_status="available",
        )
    except Exception:
        return response
    try:
        visible = _visible(_controls(config))
        response["visibility_status"] = "available"
    except bridge.AdminError:
        return response
    active = set(config.event_history_sources)
    rows = []
    for source in snapshot.sources:
        key = (source.control_uuid, source.state_uuid)
        names = visible.get(key)
        if names is None:
            continue
        rows.append(
            {
                "control_uuid": key[0],
                "state_uuid": key[1],
                "control_name": names[0],
                "control_type": names[1],
                "state_name": names[2],
                "recording_status": "active" if key in active else "removed",
                "event_count": source.event_count,
                "oldest_event_at": source.oldest_event_at,
                "newest_event_at": source.newest_event_at,
                "capture_started_at": source.capture_started_at,
                "coverage_ended_at": source.coverage_ended_at,
                "recording_ended_at": None if key in active else source.recording_ended_at,
                "recent_coverage": [
                    {"started_at": start, "ended_at": end, "outcome": outcome}
                    for start, end, outcome in source.recent_coverage
                ],
            }
        )
    response["sources"] = rows[: _SOURCE_LIMIT * 2]
    response["sources_truncated"] = snapshot.truncated
    response["hidden_sources_present"] = len(rows) < len(snapshot.sources)
    response["visible_event_count"] = sum(row["event_count"] for row in rows)
    response["visible_removed_count"] = sum(row["recording_status"] == "removed" for row in rows)
    response["visible_active_count"] = sum(row["recording_status"] == "active" for row in rows)
    return response


def quick_summary() -> dict[str, Any]:
    """Return cheap local measurements before Miniserver visibility is checked."""
    config = _bridge()._config_store().load()
    path = Path(os.getenv("MCPSERVER_EVENT_HISTORY_STORE", ""))
    size: int | None = None
    if path.is_absolute() and path.suffix == ".sqlite3":
        with suppress(OSError):
            size = sum(
                candidate.stat().st_size
                for candidate in (path, path.with_suffix(".sqlite3-wal"))
                if candidate.exists()
            )
    return {
        "enabled": config.event_history_enabled,
        "active_source_count": len(config.event_history_sources),
        "retention_days": config.event_history_retention_days,
        "maximum_mib": config.event_history_maximum_mib,
        "size_bytes": size,
        "measured_at": time.time(),
    }


def discover(payload: object) -> dict[str, Any]:
    bridge = _bridge()
    if not isinstance(payload, dict) or not isinstance(payload.get("query", ""), str):
        raise bridge.AdminError("search is invalid")
    query = payload.get("query", "").strip().casefold()
    if len(query) > 100:
        raise bridge.AdminError("search is too long")
    config = bridge._config_store().load()
    controls = _controls(config)
    matches = [
        control
        for control in controls
        if control.control_type != "Daytimer"
        and control.state_uuids
        and (not query or query in control.name.casefold() or query in control.uuid.casefold())
    ]
    matches.sort(key=lambda control: (control.name.casefold(), control.uuid))
    return {
        "controls": [
            {
                "name": control.name,
                "type": control.control_type,
                "uuid": control.uuid,
            }
            for control in matches[:100]
        ],
        "more": len(matches) > 100,
    }


def discover_states(payload: object) -> dict[str, Any]:
    """Search one currently visible control's exact state identifiers on demand."""
    bridge = _bridge()
    if not isinstance(payload, dict) or not isinstance(payload.get("query", ""), str):
        raise bridge.AdminError("search is invalid")
    query = payload.get("query", "").strip().casefold()
    if len(query) > 100:
        raise bridge.AdminError("search is too long")
    try:
        control_uuid = normalize_loxone_uuid(payload.get("control_uuid"))
    except (TypeError, ValueError) as exc:
        raise bridge.AdminError("control is invalid") from exc
    config = bridge._config_store().load()
    control = next(
        (
            item
            for item in _controls(config)
            if item.uuid == control_uuid and item.control_type != "Daytimer"
        ),
        None,
    )
    if control is None:
        raise bridge.AdminError("control is not currently visible", code="not_found")
    matches = [
        (name, uuid)
        for name, uuid in control.state_uuids
        if not query or query in name.casefold() or query in uuid.casefold()
    ]
    matches.sort(key=lambda item: (item[0].casefold(), item[1]))
    return {
        "states": [{"name": name, "uuid": uuid} for name, uuid in matches[:100]],
        "more": len(matches) > 100,
    }


def save_policy(payload: object) -> dict[str, Any]:
    bridge = _bridge()
    if not isinstance(payload, dict):
        raise bridge.AdminError("policy is invalid")
    days = payload.get("retention_days")
    size = payload.get("maximum_mib")
    if type(days) is not int or not 1 <= days <= 365:
        raise bridge.AdminError("retention must be between 1 and 365 days")
    if type(size) is not int or not 16 <= size <= 1024:
        raise bridge.AdminError("size must be between 16 and 1024 MiB")
    updated, changed = _apply(
        lambda current: replace(
            current, event_history_retention_days=days, event_history_maximum_mib=size
        )
    )
    return {
        "changed": changed,
        "retention_days": updated.event_history_retention_days,
        "maximum_mib": updated.event_history_maximum_mib,
    }


def change_source(payload: object, *, add: bool) -> dict[str, Any]:
    bridge = _bridge()
    key = _source(payload)
    config = bridge._config_store().load()
    if key not in _visible(_controls(config)):
        raise bridge.AdminError("source is not currently visible", code="not_found")
    if not add:
        _confirmed(payload)

    def change(current: PluginConfig) -> PluginConfig:
        _require_same_visibility_context(config, current)
        if add and not current.event_history_enabled:
            raise bridge.AdminError("local event history is disabled", code="feature_disabled")
        sources = current.event_history_sources
        if add:
            if key in sources:
                return current
            if len(sources) >= _SOURCE_LIMIT:
                raise bridge.AdminError("source capacity reached", code="rate_limited")
            return replace(current, event_history_sources=(*sources, key))
        if key not in sources:
            return current
        return replace(current, event_history_sources=tuple(s for s in sources if s != key))

    updated, changed = _apply(change)
    if not add:
        try:
            _store(updated).mark_removed(
                key[0], key[1], removed_at=time.time() if changed else None
            )
        except Exception as exc:
            raise bridge.AdminError(
                "source is inactive; removal metadata outcome is unknown", code="outcome_unknown"
            ) from exc
    return {"changed": changed, "recording_status": "active" if add else "removed"}


def purge_source(payload: object) -> dict[str, Any]:
    bridge = _bridge()
    _confirmed(payload)
    key = _source(payload)
    config = bridge._config_store().load()
    if key not in _visible(_controls(config)):
        raise bridge.AdminError("source is not currently visible", code="not_found")

    def operation(current: PluginConfig, _save: Any) -> tuple[int, int]:
        _require_same_visibility_context(config, current)
        if key in current.event_history_sources:
            raise bridge.AdminError("stop recording before deleting a source")
        return _store(current).purge_source(*key)

    try:
        events, coverage = bridge._config_store().transaction(operation)
    except bridge.AdminError:
        raise
    except Exception as exc:
        raise bridge.AdminError("purge outcome is unknown", code="outcome_unknown") from exc
    return {"deleted_events": events, "coverage_removed": coverage > 0}
