from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mcpserver.config import PluginConfig
from mcpserver.emergency_stop import EmergencyStopMonitor, _sorted_virtual_status_options


def test_virtual_status_options_are_sorted_case_insensitively_with_a_stable_tie_breaker() -> None:
    options = [
        {"uuid": "b", "name": "Zulu"},
        {"uuid": "z", "name": "alpha"},
        {"uuid": "a", "name": "Alpha"},
    ]

    assert _sorted_virtual_status_options(options) == [
        {"uuid": "a", "name": "Alpha"},
        {"uuid": "z", "name": "alpha"},
        {"uuid": "b", "name": "Zulu"},
    ]


def test_emergency_stop_enables_only_for_a_confirmed_one_value() -> None:
    monitor = EmergencyStopMonitor(
        PluginConfig(emergency_stop_virtual_status_uuid="00112233-4455-6677-8899aabbccddeeff")
    )

    monitor.apply(1)
    assert monitor.allows_tool_calls is True
    monitor.apply(0)
    assert monitor.allows_tool_calls is False
    monitor.apply("1")
    assert monitor.status == "unknown"


def test_emergency_stop_provider_receives_the_loxberry_perl_runtime(monkeypatch, tmp_path) -> None:
    plugin_bin = tmp_path / "bin"
    plugin_bin.mkdir()
    helper = plugin_bin / "emergency-stop-miniserver.php"
    helper.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    loxberry_home = tmp_path / "loxberry"
    perl_library = loxberry_home / "libs" / "perllib"
    perl_library.mkdir(parents=True)
    monkeypatch.setenv("MCPSERVER_BIN_DIR", str(plugin_bin))
    monkeypatch.setenv("LBHOMEDIR", str(loxberry_home))
    captured = {}

    def run(argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"username": "provider-user", "password": "provider-password"}),
        )

    monkeypatch.setattr("mcpserver.emergency_stop.subprocess.run", run)
    monitor = EmergencyStopMonitor(PluginConfig(loxone_endpoint="http://miniserver.test"))

    assert asyncio.run(monitor._credentials()) == ("provider-user", "provider-password")
    assert captured["argv"] == [
        "perl",
        "-I",
        str(perl_library),
        str(helper),
        "http://miniserver.test",
    ]
    assert captured["env"]["LBHOMEDIR"] == str(loxberry_home)
    assert captured["env"]["PERL5LIB"] == str(perl_library)


def test_emergency_stop_provider_recovers_from_an_unexpanded_service_bin_path(
    monkeypatch, tmp_path
) -> None:
    loxberry_home = tmp_path / "loxberry"
    plugin_bin = loxberry_home / "bin" / "plugins" / "mcpserver"
    plugin_bin.mkdir(parents=True)
    helper = plugin_bin / "emergency-stop-miniserver.php"
    helper.write_text("#!/usr/bin/perl\n", encoding="utf-8")
    (loxberry_home / "libs" / "perllib").mkdir(parents=True)
    config_path = loxberry_home / "config" / "plugins" / "mcpserver" / "mcpserver.json"
    monkeypatch.setenv("MCPSERVER_BIN_DIR", "@BIN_DIR@")
    monkeypatch.setenv("MCPSERVER_CONFIG", str(config_path))
    monkeypatch.setenv("LBHOMEDIR", str(loxberry_home))

    def run(argv, **_kwargs):
        assert argv[3] == str(helper)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"username": "provider-user", "password": "provider-password"}),
        )

    monkeypatch.setattr("mcpserver.emergency_stop.subprocess.run", run)
    monitor = EmergencyStopMonitor(PluginConfig(loxone_endpoint="http://miniserver.test"))

    assert asyncio.run(monitor._credentials()) == ("provider-user", "provider-password")
