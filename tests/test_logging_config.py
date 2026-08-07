from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from mcpserver.server import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    LOG_MAX_RECORD_BYTES,
    LOG_TRUNCATION_SUFFIX,
    BoundedLogFormatter,
    ServiceLevelFilter,
    _remove_stale_log_backups,
    configure_service_logging,
)


def _record(level: int, *, audit: bool = False) -> logging.LogRecord:
    record = logging.LogRecord("test", level, __file__, 1, "message", (), None)
    if audit:
        record.mcp_audit = True  # type: ignore[attr-defined]
    return record


@pytest.mark.parametrize(
    ("level", "accepted", "rejected"),
    [
        ("off", None, logging.CRITICAL),
        ("error", logging.ERROR, logging.WARNING),
        ("warning", logging.WARNING, logging.INFO),
        ("info", logging.INFO, logging.DEBUG),
        ("debug", logging.DEBUG, None),
    ],
)
def test_persistent_service_levels_are_applied(
    level: str, accepted: int | None, rejected: int | None
) -> None:
    filter_ = ServiceLevelFilter(level)

    if accepted is not None:
        assert filter_.filter(_record(accepted)) is True
    if rejected is not None:
        assert filter_.filter(_record(rejected)) is False
    assert filter_.filter(_record(logging.INFO, audit=True)) is True


def test_rendered_service_record_is_bounded() -> None:
    formatter = BoundedLogFormatter("%(message)s")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "ä" * 8_000, (), None)

    rendered = formatter.format(record)

    assert len(rendered.encode("utf-8")) <= LOG_MAX_RECORD_BYTES
    assert rendered.endswith(LOG_TRUNCATION_SUFFIX)


def test_service_file_handler_is_size_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    options: dict[str, object] = {}
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: options.update(kwargs))

    handler = configure_service_logging(
        level="warning",
        log_file=str(tmp_path / "service.log"),
    )
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == LOG_MAX_BYTES == 512 * 1024
        assert handler.backupCount == LOG_BACKUP_COUNT == 2
        assert options["level"] == logging.DEBUG
        assert options["handlers"] == [handler]
        assert options["force"] is True
        assert isinstance(handler.formatter, BoundedLogFormatter)
    finally:
        handler.close()


def test_service_rotation_keeps_only_two_backups(tmp_path: Path) -> None:
    log_file = tmp_path / "service.log"
    for suffix, value in (("", "active"), (".1", "one"), (".2", "two"), (".3", "stale")):
        (tmp_path / f"service.log{suffix}").write_text(value, encoding="utf-8")
    _remove_stale_log_backups(str(log_file))
    handler = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES, backupCount=2)
    try:
        handler.doRollover()
    finally:
        handler.close()

    assert (tmp_path / "service.log.1").read_text(encoding="utf-8") == "active"
    assert (tmp_path / "service.log.2").read_text(encoding="utf-8") == "one"
    assert not (tmp_path / "service.log.3").exists()


def test_service_start_removes_oversized_legacy_backup(tmp_path: Path) -> None:
    log_file = tmp_path / "service.log"
    oversized = tmp_path / "service.log.1"
    oversized.write_bytes(b"x" * (LOG_MAX_BYTES + 1))

    _remove_stale_log_backups(str(log_file))

    assert not oversized.exists()
