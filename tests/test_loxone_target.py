from __future__ import annotations

import io

import pytest

from tools.test_loxone_target import _read_password


def test_target_password_can_be_read_from_redirected_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tools.test_loxone_target.sys.stdin", io.StringIO("secret-value\n"))

    assert _read_password(from_stdin=True) == "secret-value"


def test_target_password_rejects_empty_redirected_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tools.test_loxone_target.sys.stdin", io.StringIO(""))

    with pytest.raises(RuntimeError, match="empty"):
        _read_password(from_stdin=True)
