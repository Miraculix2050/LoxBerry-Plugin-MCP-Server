from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from time import sleep

import pytest

from mcpserver.config import AtomicConfigStore, ConfigError, PluginConfig


def test_defaults_are_disabled_and_bounded() -> None:
    config = PluginConfig.defaults()

    assert config.enabled is False
    assert config.loxone_endpoint == ""
    assert config.loxone_read_enabled is True
    assert config.loxone_control_enabled is False
    assert config.loxberry_read_enabled is False
    assert config.loxone_history_enabled is False
    assert config.loxberry_operate_enabled is False
    assert config.connection_timeout == 10
    assert config.requests_per_minute == 60
    assert config.control_requests_per_minute == 10
    assert config.loxberry_requests_per_minute == 30
    assert config.loxberry_read_bindings == ()
    assert config.loxberry_operate_bindings == ()
    assert config.statistics_memory_max_mib == 128
    assert config.structure_refresh_seconds == 300
    assert config.max_structure_controls == 20_000
    assert config.max_parallel_calls == 4
    assert config.log_level == "warning"


def test_fresh_install_default_enables_read_only_history_and_diagnostics() -> None:
    document = json.loads(
        (Path(__file__).resolve().parents[1] / "config" / "default-config.json").read_text(
            encoding="utf-8"
        )
    )
    config = PluginConfig.from_document(document)

    assert config.enabled is False
    assert config.loxone_read_enabled is True
    assert config.loxone_history_enabled is True
    assert config.loxberry_read_enabled is True
    assert config.loxberry_read_bindings == ()


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
    assert config.to_document()["schema_version"] == 4


def test_phase_four_configuration_uses_only_the_ram_cache_setting() -> None:
    binding = "a" * 64
    config = PluginConfig.from_document(
        {
            "schema_version": 2,
            "tools": {
                "loxone_history_enabled": True,
                "loxberry_operate_enabled": True,
            },
            "limits": {
                "history_requests_per_minute": 12,
                "loxberry_operate_requests_per_minute": 2,
            },
            "cache": {"statistics_memory_max_mib": 64},
            "policies": {"loxberry_operate_bindings": [binding]},
        }
    )

    assert config.loxone_history_enabled is True
    assert config.loxberry_operate_enabled is True
    assert config.history_requests_per_minute == 12
    assert config.statistics_memory_max_mib == 64
    assert config.loxberry_operate_bindings == (binding,)


def test_removed_hybrid_cache_key_is_not_reused() -> None:
    config = PluginConfig.from_document({"schema_version": 3, "cache": {"statistics_max_mib": 64}})

    assert config.statistics_memory_max_mib == 128
    assert config.to_document()["cache"] == {"statistics_memory_max_mib": 128}


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"schema_version": 5},
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
        {"schema_version": 1, "logging": {"level": "verbose"}},
    ],
)
def test_invalid_configuration_is_rejected(document: object) -> None:
    with pytest.raises(ConfigError):
        PluginConfig.from_document(document)


def test_loxberry_operate_requires_history() -> None:
    with pytest.raises(ConfigError, match="requires loxone history"):
        PluginConfig.from_document(
            {
                "schema_version": 2,
                "tools": {"loxberry_operate_enabled": True},
            }
        )


@pytest.mark.parametrize("level", ["off", "error", "warning", "info", "debug"])
def test_all_persistent_service_levels_round_trip(level: str) -> None:
    config = PluginConfig.from_document({"schema_version": 1, "logging": {"level": level}})

    assert config.to_document()["logging"] == {"level": level}


def test_obsolete_debug_window_is_ignored_and_removed() -> None:
    config = PluginConfig.from_document(
        {
            "schema_version": 1,
            "logging": {"level": "info", "debug_until": 4_102_444_799},
        }
    )

    assert config.log_level == "info"
    assert config.to_document()["logging"] == {"level": "info"}


def test_gen2_control_configuration_is_rejected() -> None:
    with pytest.raises(ConfigError, match=r"only for Gen\. 1"):
        PluginConfig.from_document(
            {
                "schema_version": 1,
                "loxone": {"endpoint": "https://miniserver.example"},
                "tools": {"loxone_control_enabled": True},
            }
        )


@pytest.mark.parametrize(
    "bindings",
    [
        ["A" * 64],
        ["a" * 63],
        ["a" * 64, "a" * 64],
        ["a" * 64] * 65,
    ],
)
def test_invalid_loxberry_policy_bindings_are_rejected(bindings: list[str]) -> None:
    with pytest.raises(ConfigError, match="loxberry_read_bindings"):
        PluginConfig.from_document(
            {"schema_version": 1, "policies": {"loxberry_read_bindings": bindings}}
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


def test_concurrent_mutations_preserve_each_binding(tmp_path: Path) -> None:
    path = (tmp_path / "config.json").resolve()
    AtomicConfigStore(path).save(PluginConfig.defaults())
    bindings = ("a" * 64, "b" * 64)
    barrier = Barrier(len(bindings))

    def add(binding: str) -> None:
        barrier.wait()

        def operation(config: PluginConfig) -> PluginConfig:
            sleep(0.01)
            return replace(
                config,
                loxberry_read_bindings=(*config.loxberry_read_bindings, binding),
            )

        AtomicConfigStore(path).mutate(operation)

    with ThreadPoolExecutor(max_workers=len(bindings)) as executor:
        list(executor.map(add, bindings))

    assert set(AtomicConfigStore(path).load().loxberry_read_bindings) == set(bindings)
