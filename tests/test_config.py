from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcpserver.config import AtomicConfigStore, ConfigError, PluginConfig


def test_defaults_are_disabled_and_bounded() -> None:
    config = PluginConfig.defaults()

    assert config.enabled is False
    assert config.loxone_endpoint == ""
    assert config.loxone_read_enabled is True
    assert config.loxone_control_enabled is False
    assert config.connection_timeout == 10
    assert config.requests_per_minute == 60
    assert config.control_requests_per_minute == 10
    assert config.max_parallel_calls == 4
    assert config.log_level == "warning"
    assert config.debug_until == 0


def test_configuration_round_trip_preserves_unknown_keys(tmp_path: Path) -> None:
    store = AtomicConfigStore((tmp_path / "config.json").resolve())
    config = PluginConfig.from_document(
        {
            "schema_version": 1,
            "server": {"enabled": True, "public_origin": "https://loxberry.local"},
            "loxone": {"endpoint": "http://192.168.1.10"},
            "tools": {"loxone_read_enabled": True},
            "limits": {"requests_per_minute": 30, "max_parallel_calls": 2},
            "future": {"keep": True},
        }
    )

    store.save(config)

    assert store.load().to_document() == config.to_document()
    assert json.loads(store.path.read_text(encoding="utf-8"))["future"] == {"keep": True}


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"schema_version": 2},
        {"schema_version": 1, "server": {"enabled": True}},
        {
            "schema_version": 1,
            "server": {"enabled": False},
            "limits": {"requests_per_minute": 0},
        },
        {
            "schema_version": 1,
            "server": {"enabled": False},
            "loxone": {"endpoint": "http://public.example"},
        },
        {"schema_version": 1, "logging": {"level": "debug"}},
        {"schema_version": 1, "logging": {"debug_until": -1}},
    ],
)
def test_invalid_configuration_is_rejected(document: object) -> None:
    with pytest.raises(ConfigError):
        PluginConfig.from_document(document)


def test_gen2_control_configuration_is_rejected() -> None:
    with pytest.raises(ConfigError, match="only for Gen. 1"):
        PluginConfig.from_document(
            {
                "schema_version": 1,
                "loxone": {"endpoint": "https://miniserver.example"},
                "tools": {"loxone_control_enabled": True},
            }
        )


def test_failed_save_keeps_previous_valid_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AtomicConfigStore((tmp_path / "config.json").resolve())
    original = PluginConfig.defaults()
    store.save(original)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr("mcpserver.config.os.replace", fail_replace)
    with pytest.raises(ConfigError, match="update failed"):
        store.save(
            PluginConfig.from_document(
                {
                    "schema_version": 1,
                    "server": {
                        "enabled": True,
                        "public_origin": "https://loxberry.local",
                    },
                    "loxone": {"endpoint": "http://192.168.1.20"},
                }
            )
        )

    assert store.load().to_document() == original.to_document()
