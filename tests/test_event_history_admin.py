"""Local history overview and Admin mutation contracts."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from mcpserver import admin, event_history_admin
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.event_history import EventHistoryQueryTimeout, EventHistoryStore

SOURCE = ("00000000-0000-0000-0000000000000001", "00000000-0000-0000-0000000000000002")
HIDDEN = ("00000000-0000-0000-0000000000000003", "00000000-0000-0000-0000000000000004")


def _setup(tmp_path, monkeypatch, *, sources=()):
    config_store = AtomicConfigStore((tmp_path / "config" / "mcpserver.json").resolve())
    config_store.save(
        PluginConfig(
            event_history_enabled=True,
            loxone_history_enabled=True,
            event_history_sources=sources,
        )
    )
    history = EventHistoryStore(
        (tmp_path / "history" / "state-events.sqlite3").resolve(),
        retention_days=90,
        maximum_mib=128,
    )
    monkeypatch.setattr(admin, "_config_store", lambda: config_store)
    monkeypatch.setattr(admin, "_service_active", lambda: False)
    monkeypatch.setenv("MCPSERVER_EVENT_HISTORY_STORE", str(history.path))
    monkeypatch.setattr(
        event_history_admin,
        "_controls",
        lambda _config: (
            SimpleNamespace(
                uuid=SOURCE[0],
                name="Visible",
                control_type="Switch",
                state_uuids=(("active", SOURCE[1]),),
            ),
        ),
    )
    monkeypatch.setattr(
        event_history_admin,
        "_selector_projection",
        lambda _config: {
            "controls": [
                {
                    "uuid": SOURCE[0],
                    "name": "Visible",
                    "type": "Switch",
                    "room_id": "room-1",
                    "room": "Living room",
                    "category_id": "category-1",
                    "category": "Lights",
                    "states": [["active", SOURCE[1]]],
                }
            ],
        },
    )
    return config_store, history


def test_snapshot_counts_are_exact_and_read_does_not_maintain_store(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    history.begin_coverage((SOURCE,), started_at=now - 30)
    history.record_transition(*SOURCE, observed_at=now - 20, old_value=False, new_value=True)
    history.end_coverage((SOURCE,), ended_at=now - 10, outcome="stopped")
    history.begin_coverage((SOURCE,), started_at=now - 5)
    before = history.path.stat().st_mtime_ns

    result = event_history_admin.overview()
    row = result["sources"][0]

    assert result["store_status"] == "available"
    assert result["visible_event_count"] == 1
    assert result["database_bytes"] > 0 and result["wal_bytes"] >= 0
    assert row["event_count"] == 1
    assert row["logical_value_bytes"] == len(b"falsetrue")
    assert (row["room"], row["category"], row["control_type"]) == (
        "Living room",
        "Lights",
        "Switch",
    )
    assert len(row["recent_coverage"]) == 2
    assert row["oldest_event_at"] == row["newest_event_at"]
    assert history.path.stat().st_mtime_ns == before


def test_chart_query_requires_fresh_profile_bound_visibility(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    history.record_transition(*SOURCE, observed_at=now - 5, old_value=False, new_value=True)
    document = {
        "generation": "a" * 24,
        "verified_at": int(now),
        "controls": event_history_admin._selector_projection(None)["controls"],
        "control_index": {SOURCE[0]: 0},
    }

    class Cache:
        profile = "test-profile"

        def refresh(self, discover):
            discover()
            document["verified_at"] = int(time.time())
            return document

        def read(self):
            return document

    cache = Cache()
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    selected = [{"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}]
    prepared = admin.dispatch(
        {"action": "event_history_chart_prepare", "payload": {"sources": selected}}
    )
    assert prepared["sources"][0]["room"] == "Living room"
    assert prepared["history_generation"] == history.prepare_chart_read()
    payload = {
        **selected[0],
        "generation": prepared["generation"],
        "start": now - 60,
        "end": now,
        "after_id": 0,
    }
    assert (
        admin.dispatch({"action": "event_history_chart_query", "payload": payload})["events"][0][
            "new_value"
        ]
        is True
    )
    batch = event_history_admin.chart_query({"queries": [payload]})
    assert batch["results"][0]["events"][0]["new_value"] is True
    with pytest.raises(admin.AdminError, match="timed out") as timed_out:
        event_history_admin.chart_query({"queries": [payload]}, _deadline=time.monotonic() - 1)
    assert timed_out.value.code == "query_timeout"
    with pytest.raises(admin.AdminError, match="duplicate"):
        event_history_admin.chart_query({"queries": [payload, payload]})

    document["verified_at"] = int(now - 61)
    with pytest.raises(admin.AdminError, match="refreshed"):
        event_history_admin.chart_query(payload)
    document["verified_at"] = int(now)
    document["controls"] = []
    with pytest.raises(admin.AdminError, match="not visible"):
        event_history_admin.chart_query(payload)


def test_chart_store_timeout_has_distinct_code(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    document = {
        "generation": "a" * 24,
        "verified_at": now,
        "controls": event_history_admin._selector_projection(None)["controls"],
        "control_index": {SOURCE[0]: 0},
    }
    monkeypatch.setattr(
        event_history_admin,
        "_selector_cache",
        lambda _config: SimpleNamespace(read=lambda: document),
    )

    def timed_out(*_args, **_kwargs):
        raise EventHistoryQueryTimeout("chart query timed out")

    monkeypatch.setattr(EventHistoryStore, "chart_page", timed_out)
    payload = {
        "control_uuid": SOURCE[0],
        "state_uuid": SOURCE[1],
        "generation": document["generation"],
        "start": now - 60,
        "end": now,
        "after_id": 0,
    }
    with pytest.raises(admin.AdminError, match="timed out") as error:
        event_history_admin.chart_query(payload)
    assert error.value.code == "query_timeout"


def test_chart_prepare_phase_diagnostics_are_value_free(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    document = {
        "generation": "c" * 24,
        "verified_at": time.time(),
        "controls": event_history_admin._selector_projection(None)["controls"],
        "control_index": {SOURCE[0]: 0},
    }

    class Cache:
        profile = "private-profile-marker"

        def refresh(self, discover):
            discover()
            return document

    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: Cache())
    timing: dict[str, float | int] = {}

    event_history_admin.chart_prepare(
        {"sources": [{"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}]},
        timing=timing,
    )

    assert set(timing) == {
        "config_load_ms",
        "selector_refresh_ms",
        "revalidation_ms",
        "history_prepare_ms",
        "selected_sources",
        "discovered_controls",
    }
    assert all(isinstance(value, (int, float)) and value >= 0 for value in timing.values())
    diagnostics = repr(timing)
    for private_value in (*SOURCE, "Visible", "Living room", "private-profile-marker"):
        assert private_value not in diagnostics


def test_chart_selection_and_range_are_bounded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    selected = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}
    with pytest.raises(admin.AdminError):
        event_history_admin.chart_prepare({"sources": [selected] * 5})
    with pytest.raises(admin.AdminError):
        event_history_admin.chart_query({**selected, "start": 0, "end": 91 * 86400, "after_id": 0})


def test_chart_batch_reuses_one_config_visibility_and_store(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch, sources=(SOURCE, HIDDEN))
    history.initialize()
    now = time.time()
    template = event_history_admin._selector_projection(None)["controls"][0]
    hidden = {**template, "uuid": HIDDEN[0], "states": [["active", HIDDEN[1]]]}
    document = {
        "generation": "b" * 24,
        "verified_at": now,
        "controls": [template, hidden],
        "control_index": {SOURCE[0]: 0, HIDDEN[0]: 1},
    }
    calls = {"config": 0, "visibility": 0, "store": 0}
    original_load = config_store.load
    original_config = original_load()
    original_store = event_history_admin._store

    def load():
        calls["config"] += 1
        return original_load()

    def read():
        calls["visibility"] += 1
        return dict(document)

    def store(config):
        calls["store"] += 1
        return original_store(config)

    monkeypatch.setattr(config_store, "load", load)
    monkeypatch.setattr(
        event_history_admin,
        "_selector_cache",
        lambda _config: SimpleNamespace(read=read, profile="same-profile"),
    )
    monkeypatch.setattr(event_history_admin, "_store", store)
    queries = [
        {
            "control_uuid": source[0],
            "state_uuid": source[1],
            "generation": document["generation"],
            "start": now - 60,
            "end": now,
            "after_id": 0,
        }
        for source in (SOURCE, HIDDEN)
    ]
    result = event_history_admin.chart_query({"queries": queries})
    assert len(result["results"]) == 2
    assert calls == {"config": 2, "visibility": 2, "store": 1}
    original_page = EventHistoryStore.chart_page
    page_calls = 0

    def revoke_during_first_page(self, *args, **kwargs):
        nonlocal page_calls
        result = original_page(self, *args, **kwargs)
        page_calls += 1
        if page_calls == 1:
            document["generation"] = "c" * 24
        return result

    monkeypatch.setattr(EventHistoryStore, "chart_page", revoke_during_first_page)
    with pytest.raises(admin.AdminError, match="refreshed") as revoked:
        event_history_admin.chart_query({"queries": queries})
    assert revoked.value.code == "stale_configuration"
    document["generation"] = "b" * 24
    monkeypatch.setattr(EventHistoryStore, "chart_page", original_page)

    def endpoint_changes_during_first_page(self, *args, **kwargs):
        result = original_page(self, *args, **kwargs)
        config_store.save(replace(original_config, loxone_endpoint="https://other.example"))
        return result

    monkeypatch.setattr(EventHistoryStore, "chart_page", endpoint_changes_during_first_page)
    with pytest.raises(admin.AdminError, match="configuration changed") as endpoint_changed:
        event_history_admin.chart_query({"queries": queries})
    assert endpoint_changed.value.code == "stale_configuration"
    config_store.save(original_config)
    monkeypatch.setattr(EventHistoryStore, "chart_page", original_page)
    queries[1]["generation"] = "c" * 24
    with pytest.raises(admin.AdminError, match="refreshed"):
        event_history_admin.chart_query({"queries": queries})
    queries[1]["generation"] = document["generation"]
    document["controls"].pop()
    before_store = calls["store"]
    with pytest.raises(admin.AdminError, match="not visible"):
        event_history_admin.chart_query({"queries": queries})
    assert calls["store"] == before_store


def test_quick_summary_avoids_miniserver_discovery(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: pytest.fail("discovery"))

    result = event_history_admin.quick_summary()

    assert result["active_source_count"] == 1
    assert result["size_bytes"] == history.path.stat().st_size


def test_empty_overview_avoids_miniserver_discovery(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch)
    history.initialize()
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: pytest.fail("discovery"))

    result = event_history_admin.overview()

    assert result["store_status"] == "available"
    assert result["visibility_status"] == "available"
    assert result["visible_active_count"] == 0
    assert result["unverified_sources"] == []


def test_admin_discovery_uses_endpoint_bound_auth_breaker(tmp_path, monkeypatch):
    config_store, _ = _setup(tmp_path, monkeypatch)
    auth_path = (tmp_path / "auth" / "sessions.json").resolve()
    seen = []

    def pseudonym(*parts):
        seen.append(parts)
        return "test-profile"

    monkeypatch.setattr(
        admin,
        "_auth_store",
        lambda: SimpleNamespace(path=auth_path, pseudonym=pseudonym),
    )
    config = replace(config_store.load(), loxone_endpoint="https://miniserver.example")
    monitor = event_history_admin._monitor(config)

    assert monitor.auth_coordinator is not None
    assert monitor.auth_coordinator._path == auth_path.parent / "miniserver-auth-diagnostics.json"
    assert monitor.auth_coordinator._profile_id == "test-profile"
    assert seen == [("miniserver-auth-profile-v1", "https://miniserver.example")]


def test_v2_migration_rebuilds_exact_event_summaries(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    history.record_transition(*SOURCE, observed_at=now - 1, old_value=0, new_value=1)
    with sqlite3.connect(history.path) as db:
        db.execute("DROP TABLE source_totals")
        db.execute("PRAGMA user_version=2")

    history.initialize()
    assert history.snapshot((SOURCE,)).sources[0].event_count == 1


def test_v3_migration_preserves_events_and_adds_clear_generation(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    with sqlite3.connect(history.path) as db:
        db.execute("DROP TABLE history_metadata")
        db.execute("PRAGMA user_version=3")

    revision = admin.dispatch({"action": "event_history_source_revision"})
    assert revision["availability"] == "available"
    snapshot = history.snapshot((SOURCE,))
    assert snapshot.sources[0].event_count == 1
    assert snapshot.clear_generation == 0
    history.clear()
    assert history.snapshot((SOURCE,)).clear_generation == 1


def test_overview_hides_historical_metadata_for_invisible_sources(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    history.record_transition(*SOURCE, observed_at=now - 2, old_value=0, new_value=1)
    history.record_transition(*HIDDEN, observed_at=now - 2, old_value=0, new_value=1)
    history.mark_removed(*HIDDEN, removed_at=now - 1)

    result = event_history_admin.overview()

    assert [item["control_uuid"] for item in result["sources"]] == [SOURCE[0]]
    assert result["unverified_sources"] == []
    assert result["visible_event_count"] == 1
    assert result["database_bytes"] > 0


def test_visible_overview_uses_fresh_selector_without_new_discovery(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    projection = event_history_admin._selector_projection(None)
    document = {
        "generation": "a" * 24,
        "verified_at": int(time.time()),
        "controls": projection["controls"],
    }
    cache = SimpleNamespace(profile="test-profile", read=lambda: document)
    monkeypatch.setattr(event_history_admin, "_selector_cache", lambda _config: cache)
    monkeypatch.setattr(
        event_history_admin,
        "_selector_projection",
        lambda _config: pytest.fail("new discovery is unnecessary"),
    )
    result = event_history_admin.visible_overview()
    assert result["sources"][0]["event_count"] == 1
    document["verified_at"] -= 61
    with pytest.raises(admin.AdminError) as stale:
        event_history_admin.visible_overview()
    assert stale.value.code == "stale_configuration"


def test_overview_uses_current_nullable_context_and_revokes_it(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    projection = event_history_admin._selector_projection(None)
    control = projection["controls"][0]
    control.update(room_id=None, room=None, category_id=None, category=None)
    monkeypatch.setattr(event_history_admin, "_selector_projection", lambda _config: projection)

    row = event_history_admin.overview()["sources"][0]
    assert (row["room_id"], row["room"], row["category_id"], row["category"]) == (
        None,
        None,
        None,
        None,
    )

    projection["controls"] = []
    revoked = event_history_admin.overview()
    assert revoked["sources"] == []
    assert revoked["unverified_sources"] == [{"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}]


def test_invisible_configured_source_can_be_stopped_without_discovery(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch, sources=(HIDDEN,))
    history.initialize()
    result = event_history_admin.overview()
    assert result["sources"] == []
    assert result["unverified_sources"] == [{"control_uuid": HIDDEN[0], "state_uuid": HIDDEN[1]}]
    assert result["hidden_sources_present"] is True

    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: pytest.fail("discovery"))
    key = {"control_uuid": HIDDEN[0], "state_uuid": HIDDEN[1], "confirm": True}
    assert event_history_admin.change_source(key, add=False)["changed"] is True
    assert config_store.load().event_history_sources == ()
    with pytest.raises(admin.AdminError) as missing:
        event_history_admin.change_source(key, add=False)
    assert missing.value.code == "not_found"


def test_overview_keeps_configured_source_removal_available_when_visibility_fails(
    tmp_path, monkeypatch
):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()

    def unavailable(_config):
        raise admin.AdminError("structure unavailable", code="temporarily_unavailable")

    monkeypatch.setattr(event_history_admin, "_selector_projection", unavailable)
    result = event_history_admin.overview()
    assert result["visibility_status"] == "unavailable"
    assert result["unverified_sources"] == [{"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}]


def test_local_overview_reports_sources_without_retrying_miniserver(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: pytest.fail("discovery"))

    result = admin.dispatch({"action": "event_history_local_overview", "payload": {}})

    assert result["store_status"] == "available"
    assert result["visibility_status"] == "unavailable"
    assert result["sources"] == []
    assert result["unverified_sources"] == [{"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}]


def test_source_actions_preserve_history_until_separate_confirmed_purge(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch)
    history.initialize()
    now = time.time()
    history.record_transition(*SOURCE, observed_at=now - 1, old_value=0, new_value=1)
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}

    assert event_history_admin.change_source(key, add=True)["changed"]
    with pytest.raises(admin.AdminError) as required:
        event_history_admin.change_source(key, add=False)
    assert required.value.code == "confirmation_required"
    assert event_history_admin.change_source({**key, "confirm": True}, add=False)["changed"]
    assert config_store.load().event_history_sources == ()
    assert history.snapshot(()).sources[0].event_count == 1
    with pytest.raises(admin.AdminError) as required:
        event_history_admin.purge_source(key)
    assert required.value.code == "confirmation_required"
    assert event_history_admin.purge_source({**key, "confirm": True})["deleted_events"] == 1
    assert history.snapshot(()).sources == ()


def test_add_returns_fresh_visible_overview_without_second_discovery(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch)
    history.initialize()
    original_projection = event_history_admin._selector_projection
    discoveries = 0

    def projection(config):
        nonlocal discoveries
        discoveries += 1
        return original_projection(config)

    monkeypatch.setattr(event_history_admin, "_selector_projection", projection)
    result = event_history_admin.change_source(
        {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}, add=True
    )

    assert discoveries == 1
    assert result["changed"] is True
    assert result["overview"]["visibility_status"] == "available"
    assert result["overview"]["visible_active_count"] == 1
    assert result["overview"]["sources"][0]["control_name"] == "Visible"
    assert result["overview"]["sources"][0]["state_name"] == "active"
    assert config_store.load().event_history_sources == (SOURCE,)


def test_source_revision_tracks_membership_without_polling_event_changes(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch)
    history.initialize()
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}

    def revision():
        return admin.dispatch({"action": "event_history_source_revision"})["revision"]

    initial = revision()

    added = event_history_admin.change_source(key, add=True)
    active = revision()
    assert active != initial
    assert added["overview"]["source_revision"] == active

    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    assert revision() == active

    history.clear()
    cleared = revision()
    assert cleared != active
    assert config_store.load().event_history_sources == (SOURCE,)
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=1, new_value=2)
    assert revision() == cleared

    event_history_admin.change_source({**key, "confirm": True}, add=False)
    removed = revision()
    assert removed != active
    event_history_admin.purge_source({**key, "confirm": True})
    assert revision() != removed


def test_payload_backfill_completion_signals_poll_without_changing_source_revision(
    tmp_path, monkeypatch
):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    with sqlite3.connect(history.path) as db:
        db.execute("UPDATE events SET logical_value_bytes = NULL")
        db.execute("UPDATE source_totals SET logical_value_bytes = 0, unmeasured_events = 1")
    pending = admin.dispatch({"action": "event_history_source_revision"})
    assert pending["payload_pending"] is True
    assert event_history_admin.overview()["payload_pending"] is True

    assert history.backfill_payload_batch() is False
    complete = admin.dispatch({"action": "event_history_source_revision"})
    assert complete["revision"] == pending["revision"]
    assert complete["payload_pending"] is False
    overview = event_history_admin.overview()
    assert overview["payload_pending"] is False
    assert overview["sources"][0]["logical_value_bytes"] == 2


def test_snapshot_keeps_counts_and_clear_generation_consistent(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    original_connect = sqlite3.connect
    cleared = False

    class ClearDuringRead(sqlite3.Connection):
        def execute(self, sql, *args):
            nonlocal cleared
            cursor = super().execute(sql, *args)
            if sql.startswith("SELECT control_uuid, state_uuid, event_count") and not cleared:
                cleared = True
                history.clear()
            return cursor

    def connect(*args, **kwargs):
        if kwargs.get("uri"):
            kwargs["factory"] = ClearDuringRead
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    before = history.snapshot((SOURCE,))
    after = history.snapshot((SOURCE,))
    assert cleared
    assert (before.sources[0].event_count, before.clear_generation) == (1, 0)
    assert (after.sources[0].event_count, after.clear_generation) == (0, 1)


def test_policy_update_preserves_sources_and_rejects_invalid_input(tmp_path, monkeypatch):
    config_store, _ = _setup(tmp_path, monkeypatch, sources=(SOURCE,))

    with pytest.raises(admin.AdminError):
        event_history_admin.save_policy({"retention_days": 0, "maximum_mib": 128})
    assert event_history_admin.save_policy({"retention_days": 30, "maximum_mib": 64})["changed"]
    current = config_store.load()
    assert current.event_history_sources == (SOURCE,)
    assert (current.event_history_retention_days, current.event_history_maximum_mib) == (30, 64)


def test_add_rechecks_current_visibility_and_policy_rollback(tmp_path, monkeypatch):
    config_store, _ = _setup(tmp_path, monkeypatch)
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1]}
    monkeypatch.setattr(
        event_history_admin, "_selector_projection", lambda _config: {"controls": []}
    )
    with pytest.raises(admin.AdminError) as hidden:
        event_history_admin.change_source(key, add=True)
    assert hidden.value.code == "not_found"
    monkeypatch.setattr(admin, "_service_active", lambda: True)
    restarts = 0

    def restart() -> None:
        nonlocal restarts
        restarts += 1
        if restarts == 1:
            raise admin.AdminError("restart failed")

    monkeypatch.setattr(admin, "_restart_service", restart)
    with pytest.raises(admin.AdminError) as failure:
        event_history_admin.save_policy({"retention_days": 30, "maximum_mib": 64})
    assert failure.value.code == "apply_failed"
    assert restarts == 2
    assert config_store.load().event_history_retention_days == 90


def test_active_source_cannot_be_purged_even_when_confirmed(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1], "confirm": True}

    with pytest.raises(admin.AdminError) as active:
        event_history_admin.purge_source(key)

    assert active.value.code == "invalid_request"


def test_selected_source_can_be_removed_while_history_is_disabled(tmp_path, monkeypatch):
    config_store, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    config_store.save(replace(config_store.load(), event_history_enabled=False))
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1], "confirm": True}

    assert event_history_admin.change_source(key, add=False)["changed"] is True
    assert config_store.load().event_history_sources == ()


def test_state_discovery_can_find_exact_uuid_beyond_first_page(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    states = tuple((f"state {index:03d}", f"{index + 100:032x}") for index in range(150))
    monkeypatch.setattr(
        event_history_admin,
        "_controls",
        lambda _config: (
            SimpleNamespace(
                uuid=SOURCE[0], name="Visible", control_type="Switch", state_uuids=states
            ),
        ),
    )
    controls = event_history_admin.discover({"query": "Visible"})
    assert "states" not in controls["controls"][0]
    initial = event_history_admin.discover_states({"control_uuid": SOURCE[0], "query": ""})
    assert len(initial["states"]) == 100 and initial["more"] is True
    exact = event_history_admin.discover_states({"control_uuid": SOURCE[0], "query": states[-1][1]})
    assert exact == {"states": [{"name": states[-1][0], "uuid": states[-1][1]}], "more": False}


@pytest.mark.parametrize("action", ["add", "purge"])
def test_source_action_rejects_endpoint_changed_during_visibility_check(
    tmp_path, monkeypatch, action
):
    config_store, history = _setup(tmp_path, monkeypatch)
    history.initialize()
    if action == "purge":
        history.record_transition(*SOURCE, observed_at=time.time(), old_value=0, new_value=1)
    visible = (
        event_history_admin._selector_projection(config_store.load())
        if action == "add"
        else event_history_admin._controls(config_store.load())
    )

    def change_endpoint(_config):
        config_store.save(replace(config_store.load(), loxone_endpoint="https://other.example"))
        return visible

    monkeypatch.setattr(
        event_history_admin,
        "_selector_projection" if action == "add" else "_controls",
        change_endpoint,
    )
    key = {"control_uuid": SOURCE[0], "state_uuid": SOURCE[1], "confirm": True}

    with pytest.raises(admin.AdminError) as stale:
        if action == "add":
            event_history_admin.change_source(key, add=True)
        else:
            event_history_admin.purge_source(key)

    assert stale.value.code == "stale_configuration"
    assert config_store.load().event_history_sources == ()
    if action == "purge":
        assert history.snapshot(()).sources[0].event_count == 1
