from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from mcpserver.server import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    TimedLevelFilter,
    configure_service_logging,
)


def _record(level: int, *, audit: bool = False) -> logging.LogRecord:
    record = logging.LogRecord("test", level, __file__, 1, "message", (), None)
    if audit:
        record.mcp_audit = True  # type: ignore[attr-defined]
    return record


def test_debug_window_expires_to_the_configured_level() -> None:
    now = [100.0]
    filter_ = TimedLevelFilter("warning", debug_until=200, clock=lambda: now[0])

    assert filter_.filter(_record(logging.DEBUG)) is True
    now[0] = 201.0
    assert filter_.filter(_record(logging.INFO)) is False
    assert filter_.filter(_record(logging.WARNING)) is True
    assert filter_.filter(_record(logging.DEBUG, audit=True)) is True


def test_service_file_handler_is_size_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options: dict[str, object] = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: options.update(kwargs))

    handler = configure_service_logging(
        level="warning",
        debug_until=0,
        log_file=str(tmp_path / "service.log"),
    )
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == LOG_MAX_BYTES == 512 * 1024
        assert handler.backupCount == LOG_BACKUP_COUNT == 2
        assert options["level"] == logging.DEBUG
        assert options["handlers"] == [handler]
        assert options["force"] is True
    finally:
        handler.close()
