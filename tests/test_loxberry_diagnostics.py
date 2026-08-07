from __future__ import annotations

import subprocess
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
