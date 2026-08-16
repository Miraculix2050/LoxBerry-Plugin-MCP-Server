from __future__ import annotations

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
