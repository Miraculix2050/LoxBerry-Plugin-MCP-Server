"""Private selector projection and Admin discovery contracts."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mcpserver import admin, event_history_admin
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.event_history_selector_cache import EventHistorySelectorCache, SelectorCacheError
from mcpserver.loxone.event_history import EventHistoryStore

CONTROL = "00000000-0000-0000-0000000000000001"
STATE = "00000000-0000-0000-0000000000000002"


def _cache(tmp_path: Path, profile: str = "first") -> EventHistorySelectorCache:
    return EventHistorySelectorCache((tmp_path / "auth" / "sessions.json").resolve(), profile)


def _projection(count: int = 1, *, last_modified: str = "version") -> dict:
    return {
        "last_modified": last_modified,
        "controls": [
            {
                "uuid": f"00000000-0000-0000-{index + 1:016d}",
                "name": f"Control {index:04d}",
                "type": "Switch" if index % 2 == 0 else "InfoOnlyDigital",
                "room_id": "room-1" if index % 2 == 0 else None,
                "room": "Kitchen" if index % 2 == 0 else None,
                "category_id": "category-1" if index % 2 == 0 else "category-2",
                "category": "Lighting" if index % 2 == 0 else "Status",
                "states": [["active", STATE]],
            }
            for index in range(count)
        ],
    }


def test_cache_is_profile_bound_and_failed_fresh_check_hides_old_names(tmp_path):
    cache = _cache(tmp_path)
    initial = cache.refresh(lambda: _projection())
    assert cache.read()["generation"] == initial["generation"]
    assert _cache(tmp_path, "another-identity").read() is None

    def failed_discovery():
        raise TimeoutError("unavailable")

    with pytest.raises(TimeoutError):
        cache.refresh(failed_discovery)
    assert cache.read() is None
    assert cache.refresh(lambda: _projection())["controls"][0]["name"] == "Control 0000"


def test_concurrent_refreshes_share_one_result(tmp_path):
    cache = _cache(tmp_path)
    calls = []

    def discover():
        calls.append(1)
        time.sleep(0.2)
        return _projection()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cache.refresh, discover) for _ in range(2)]
        results = [future.result() for future in futures]
    assert len(calls) == 1
    assert results[0]["generation"] == results[1]["generation"]


def test_duplicate_control_identifiers_are_rejected_before_publish(tmp_path):
    cache = _cache(tmp_path)
    projection = _projection(2)
    projection["controls"][1]["uuid"] = projection["controls"][0]["uuid"]
    with pytest.raises(SelectorCacheError, match="invalid or oversized"):
        cache.refresh(lambda: projection)
    assert cache.read() is None


def test_new_page_refreshes_even_when_program_marker_is_unchanged(tmp_path):
    cache = _cache(tmp_path)
    first = cache.refresh(lambda: _projection())
    second = cache.refresh(lambda: _projection())
    assert second["last_modified"] == first["last_modified"]
    assert second["generation"] != first["generation"]


def test_large_catalog_uses_paged_queries_and_rejects_old_generation(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    projection = _projection(15_000)
    for item in projection["controls"]:
        item["name"] += " x" * 260
    first = cache.refresh(lambda: projection)
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    config_store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    config_store.save(PluginConfig())
    monkeypatch.setattr(admin, "_config_store", lambda: config_store)
    payload = {"generation": first["generation"]}

    catalog = event_history_admin.selector_catalog(payload)
    assert catalog["mode"] == "paged"
    assert catalog["total"] == 15_000
    result = event_history_admin.selector_query(
        payload | {"query": "Control 14999", "room": [], "category": [], "type": []}
    )
    assert result["total"] == 1
    assert result["controls"][0]["uuid"] == projection["controls"][-1]["uuid"]

    cache.refresh(lambda: _projection(0))
    with pytest.raises(admin.AdminError, match="selector has changed"):
        event_history_admin.selector_query(
            payload | {"query": "", "room": [], "category": [], "type": []}
        )


def test_selector_filters_full_inventory_and_bounds_states(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    projection = _projection(150)
    projection["controls"][0]["states"] = [
        [f"state {index}", f"state-{index}"] for index in range(250)
    ]
    document = cache.refresh(lambda: projection)
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    config_store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    config_store.save(PluginConfig())
    monkeypatch.setattr(admin, "_config_store", lambda: config_store)
    payload = {"generation": document["generation"]}

    result = event_history_admin.selector_query(
        payload | {"query": "Control 0149", "room": [], "category": [], "type": []}
    )
    assert result["total"] == 1
    assert result["controls"][0]["name"] == "Control 0149"
    filtered = event_history_admin.selector_query(
        payload | {"query": "", "room": ["room-1"], "category": [], "type": ["Switch"]}
    )
    assert filtered["total"] == 75
    assert len(filtered["controls"]) == 50
    assert event_history_admin.selector_facets(payload)["room"] == [
        {"id": "", "name": ""},
        {"id": "room-1", "name": "Kitchen"},
    ]
    states = event_history_admin.selector_states(
        payload | {"control_uuid": CONTROL, "query": "", "offset": 0}
    )
    assert states["total"] == 250
    assert len(states["states"]) == 200
    assert event_history_admin.selector_states(
        payload | {"control_uuid": CONTROL, "query": "state 249", "offset": 0}
    )["states"] == [{"name": "state 249", "uuid": "state-249"}]


def test_equal_room_names_remain_distinct_filter_values(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    projection = _projection(2)
    projection["controls"][1]["room_id"] = "room-2"
    projection["controls"][1]["room"] = "Kitchen"
    document = cache.refresh(lambda: projection)
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    config_store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    config_store.save(PluginConfig())
    monkeypatch.setattr(admin, "_config_store", lambda: config_store)
    payload = {"generation": document["generation"]}
    assert {item["id"] for item in event_history_admin.selector_facets(payload)["room"]} == {
        "room-1",
        "room-2",
    }
    result = event_history_admin.selector_query(
        payload | {"query": "", "room": ["room-2"], "category": [], "type": []}
    )
    assert [item["name"] for item in result["controls"]] == ["Control 0001"]


def test_prepare_rechecks_visibility_when_marker_does_not_change(tmp_path, monkeypatch):
    cache = _cache(tmp_path)
    config_store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    config_store.save(
        PluginConfig(
            loxone_endpoint="https://miniserver.example",
            loxone_history_enabled=True,
            event_history_enabled=True,
            event_history_sources=((CONTROL, STATE),),
        )
    )
    history = EventHistoryStore(
        (tmp_path / "history" / "state-events.sqlite3").resolve(),
        retention_days=90,
        maximum_mib=128,
    )
    history.initialize()
    monkeypatch.setenv("MCPSERVER_EVENT_HISTORY_STORE", str(history.path))
    monkeypatch.setattr(admin, "_config_store", lambda: config_store)
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    discoveries = iter([_projection(), _projection(0)])
    monkeypatch.setattr(
        event_history_admin, "_selector_projection", lambda _config: next(discoveries)
    )

    first = event_history_admin.prepare_selector()
    second = event_history_admin.prepare_selector()
    assert first["total"] == 1
    assert second["total"] == 0
    assert second["last_modified"] == first["last_modified"]
    assert second["generation"] != first["generation"]
    assert second["overview"]["unverified_sources"] == [
        {"control_uuid": CONTROL, "state_uuid": STATE}
    ]
