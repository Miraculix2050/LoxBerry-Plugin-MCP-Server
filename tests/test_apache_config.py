from __future__ import annotations

from pathlib import Path

from mcpserver.settings import SERVER_PORT


def test_apache_proxy_is_narrow_and_loopback_only() -> None:
    config = Path("config/apache/mcpserver.conf").read_text(encoding="utf-8")

    assert (
        f'ProxyPassMatch "^/plugins/mcpserver/(mcp)$" "http://127.0.0.1:{SERVER_PORT}/$1"' in config
    )
    assert "ProxyRequests" not in config
    assert "ProxyPreserveHost" not in config
    assert "\nProxyTimeout " not in config
    assert "timeout=300" in config
    assert "0.0.0.0" not in config
    assert "ProxyPass / " not in config


def test_apache_exposes_only_exact_oauth_and_metadata_paths() -> None:
    config = Path("config/apache/mcpserver.conf").read_text(encoding="utf-8")
    public_paths = (
        "/plugins/mcpserver/oauth/authorize",
        "/plugins/mcpserver/oauth/token",
        "/plugins/mcpserver/oauth/register",
        "/plugins/mcpserver/oauth/revoke",
        "/.well-known/oauth-protected-resource/plugins/mcpserver/mcp",
        "/.well-known/oauth-authorization-server/plugins/mcpserver/oauth",
    )

    for path in public_paths:
        leaf = path.rsplit("/", 1)[-1]
        if path.startswith("/.well-known/"):
            assert f'ProxyPassMatch "^({path})$" ' in config
        else:
            prefix = path[: -len(leaf)]
            assert f'ProxyPassMatch "^{prefix}({leaf})$" ' in config
        assert f'ProxyPassReverse "{path}" ' in config
    assert 'ProxyPassMatch "^/plugins/mcpserver/oauth$" ' not in config
    assert 'ProxyPassMatch "^/.well-known/$" ' not in config
