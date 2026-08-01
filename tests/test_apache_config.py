from __future__ import annotations

from pathlib import Path


def test_apache_proxy_is_narrow_and_loopback_only() -> None:
    config = Path("config/apache/mcpserver.conf").read_text(encoding="utf-8")

    assert 'ProxyPass "/plugins/mcpserver/mcp" "http://127.0.0.1:8765/mcp"' in config
    assert "ProxyRequests" not in config
    assert "ProxyPreserveHost" not in config
    assert "\nProxyTimeout " not in config
    assert "timeout=300" in config
    assert "0.0.0.0" not in config
    assert "ProxyPass / " not in config
