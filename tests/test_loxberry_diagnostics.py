from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mcpserver.loxberry.diagnostics import DiagnosticsUnavailable, LoxBerryDiagnostics


def test_version_reads_only_the_fixed_limited_loberry_config(tmp_path: Path) -> None:
    home = (tmp_path / "loxberry").resolve()
    config = home / "config" / "system"
    config.mkdir(parents=True)
    (config / "general.json").write_text('{"Base":{"Version":"4.0.0.14"}}', encoding="utf-8")

    assert LoxBerryDiagnostics(home)._version() == "4.0.0.14"


def test_version_rejects_invalid_or_oversized_config(tmp_path: Path) -> None:
    home = (tmp_path / "loxberry").resolve()
    config = home / "config" / "system"
    config.mkdir(parents=True)
    target = config / "general.json"
    target.write_text("{}", encoding="utf-8")
    diagnostics = LoxBerryDiagnostics(home)
    with pytest.raises(DiagnosticsUnavailable):
        diagnostics._version()
    target.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(DiagnosticsUnavailable):
        diagnostics._version()


def test_service_health_uses_fixed_command_and_masks_missing_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(
            command, 0, b"LoadState=loaded\nActiveState=active\nSubState=running\n"
        )

    monkeypatch.setattr("mcpserver.loxberry.diagnostics.subprocess.run", run)
    result = LoxBerryDiagnostics(tmp_path.resolve()).service_health()

    assert captured["command"][-1] == "loxberry-mcpserver.service"
    assert captured["timeout"] == 3
    assert result == {
        "service_name": "loxberry-mcpserver",
        "installed": True,
        "active_state": "active",
        "sub_state": "running",
        "healthy": True,
    }


def test_service_events_return_only_allowlisted_fields_from_fixed_log(tmp_path: Path) -> None:
    log = tmp_path / "log" / "plugins" / "mcpserver"
    log.mkdir(parents=True)
    (log / "service.log").write_text(
        "2026-08-14 10:00:00,000 component=mcpserver.tools severity=ERROR "
        "component=tools outcome=internal_error tool=secret error_type=ValueError\n"
        "not an event and definitely not returned\n",
        encoding="utf-8",
    )

    assert LoxBerryDiagnostics(tmp_path.resolve()).service_events() == [
        {
            "timestamp": "2026-08-14 10:00:00,000",
            "component": "mcpserver.tools",
            "severity": "error",
            "outcome": "internal_error",
            "error_type": "ValueError",
        }
    ]


def test_service_events_filter_and_reject_invalid_input_or_oversized_log(tmp_path: Path) -> None:
    log = tmp_path / "log" / "plugins" / "mcpserver"
    log.mkdir(parents=True)
    target = log / "service.log"
    target.write_text(
        (
            "2026-08-14T10:00:00Z component=mcpserver.tools severity=ERROR "
            "trace_id=trace-1 outcome=failed\n"
            "2026-08-14T11:00:00Z component=mcpserver.service severity=INFO "
            "trace_id=trace-2 outcome=ok\n"
        ),
        encoding="utf-8",
    )
    diagnostics = LoxBerryDiagnostics(tmp_path.resolve())
    with pytest.raises(ValueError):
        diagnostics.service_events(component="not-allowed")
    assert diagnostics.service_events(trace_id="trace-1", severity="error") == [
        {
            "timestamp": "2026-08-14T10:00:00Z",
            "component": "mcpserver.tools",
            "severity": "error",
            "trace_id": "trace-1",
            "outcome": "failed",
        }
    ]
    assert diagnostics.service_events(
        start=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        end=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
    ) == [
        {
            "timestamp": "2026-08-14T10:00:00Z",
            "component": "mcpserver.tools",
            "severity": "error",
            "trace_id": "trace-1",
            "outcome": "failed",
        }
    ]
    with pytest.raises(ValueError, match="event interval"):
        diagnostics.service_events(
            start=datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
            end=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        )
    target.write_bytes(b"x" * (512 * 1024 + 1))
    with pytest.raises(DiagnosticsUnavailable):
        diagnostics.service_events()


def test_diagnostic_source_rejects_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.log"
    target.write_text("safe", encoding="utf-8")
    source = tmp_path / "source.log"
    try:
        source.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    with pytest.raises(DiagnosticsUnavailable):
        LoxBerryDiagnostics._read_limited(source, 64)
