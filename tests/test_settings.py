from __future__ import annotations

import pytest

from mcpserver.settings import ServerSettings


def test_secure_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "MCPSERVER_HOST",
        "MCPSERVER_PORT",
        "MCPSERVER_ALLOWED_HOSTS",
        "MCPSERVER_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = ServerSettings.from_environment()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.allowed_hosts == ("127.0.0.1:8765", "localhost:8765")
    assert settings.allowed_origins == ()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.10"])
def test_non_loopback_bind_is_rejected(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("MCPSERVER_HOST", host)
    with pytest.raises(ValueError, match="must remain 127.0.0.1"):
        ServerSettings.from_environment()


@pytest.mark.parametrize("port", ["abc", "0", "1023", "65536"])
def test_invalid_port_is_rejected(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("MCPSERVER_PORT", port)
    with pytest.raises(ValueError, match="MCPSERVER_PORT"):
        ServerSettings.from_environment()


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://example.test",
        "https://user@example.test",
        "https://:secret@example.test",
        "https://example.test/",
        "https://example.test/path",
    ],
)
def test_invalid_origin_is_rejected(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_ORIGINS", origin)
    with pytest.raises(ValueError, match="MCPSERVER_ALLOWED_ORIGINS"):
        ServerSettings.from_environment()
