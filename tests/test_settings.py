from __future__ import annotations

from pathlib import Path

import pytest

from mcpserver.settings import ServerSettings


def test_arm64_runtime_lock_contains_no_windows_only_packages() -> None:
    lock_path = Path(__file__).parents[1] / "requirements" / "runtime-arm64.lock"

    assert "pywin32" not in lock_path.read_text(encoding="utf-8").lower()


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
    with pytest.raises(ValueError, match=r"must remain 127\.0\.0\.1"):
        ServerSettings.from_environment()


@pytest.mark.parametrize("port", ["abc", "8766", "08765"])
def test_non_proxy_port_is_rejected(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    monkeypatch.setenv("MCPSERVER_PORT", port)
    with pytest.raises(ValueError, match="must remain 8765"):
        ServerSettings.from_environment()


@pytest.mark.parametrize(
    "hosts",
    [
        "https://loxberry.local",
        "loxberry.local:*:443",
        "user@loxberry.local",
        "loxberry.local/path",
        "EXAMPLE.local:8765",
    ],
)
def test_invalid_allowed_host_is_rejected(monkeypatch: pytest.MonkeyPatch, hosts: str) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_HOSTS", hosts)

    with pytest.raises(ValueError, match="MCPSERVER_ALLOWED_HOSTS"):
        ServerSettings.from_environment()


def test_canonical_allowed_hosts_are_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MCPSERVER_ALLOWED_HOSTS",
        "loxberry.local,loxberry.local:8765,loxberry.local:*,[2001:db8::1]:8765",
    )

    settings = ServerSettings.from_environment()

    assert settings.allowed_hosts == (
        "loxberry.local",
        "loxberry.local:8765",
        "loxberry.local:*",
        "[2001:db8::1]:8765",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://example.test",
        "https://user@example.test",
        "https://:secret@example.test",
        "https://example.test/",
        "https://example.test/path",
        "https://client.example:443",
        "http://client.example:80",
        "HTTPS://client.example",
        "https://bücher.example",
        "https://[2001:0db8:0:0:0:0:0:1]",
        "https://[::ffff:192.168.1.1]",
        "https://example%2ecom",
        "https://example.com\\evil",
        "https://127.1",
        "https://0177.0.0.1",
        "https://0x7f000001",
        "https://xn--a.example",
    ],
)
def test_invalid_origin_is_rejected(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_ORIGINS", origin)
    with pytest.raises(ValueError, match="MCPSERVER_ALLOWED_ORIGINS"):
        ServerSettings.from_environment()


def test_canonical_non_default_origin_port_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_ORIGINS", "https://client.example:8443")

    settings = ServerSettings.from_environment()

    assert settings.allowed_origins == ("https://client.example:8443",)


def test_canonical_idna_origin_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MCPSERVER_ALLOWED_ORIGINS",
        "https://xn--bcher-kva.example,https://xn--fa-hia.de,https://xn--3xa.gr",
    )

    settings = ServerSettings.from_environment()

    assert settings.allowed_origins == (
        "https://xn--bcher-kva.example",
        "https://xn--fa-hia.de",
        "https://xn--3xa.gr",
    )


def test_canonical_ipv6_origin_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_ORIGINS", "https://[2001:db8::1]")

    settings = ServerSettings.from_environment()

    assert settings.allowed_origins == ("https://[2001:db8::1]",)


def test_browser_canonical_ipv4_mapped_ipv6_origin_is_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCPSERVER_ALLOWED_ORIGINS", "https://[::ffff:c0a8:101]")

    settings = ServerSettings.from_environment()

    assert settings.allowed_origins == ("https://[::ffff:c0a8:101]",)
