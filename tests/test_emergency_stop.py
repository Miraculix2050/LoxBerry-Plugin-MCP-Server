from __future__ import annotations

from mcpserver.emergency_stop import _sorted_virtual_status_options


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
