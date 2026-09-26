"""Local history overview and Admin mutation contracts."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from mcpserver import admin, event_history_admin
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.event_history import EventHistoryStore

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
    assert len(row["recent_coverage"]) == 2
    assert row["oldest_event_at"] == row["newest_event_at"]
    assert history.path.stat().st_mtime_ns == before


def test_quick_summary_avoids_miniserver_discovery(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: pytest.fail("discovery"))

    result = event_history_admin.quick_summary()

    assert result["active_source_count"] == 1
    assert result["size_bytes"] == history.path.stat().st_size


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


def test_overview_hides_historical_metadata_for_invisible_sources(tmp_path, monkeypatch):
    _, history = _setup(tmp_path, monkeypatch, sources=(SOURCE,))
    history.initialize()
    now = time.time()
    history.record_transition(*SOURCE, observed_at=now - 2, old_value=0, new_value=1)
    history.record_transition(*HIDDEN, observed_at=now - 2, old_value=0, new_value=1)
    history.mark_removed(*HIDDEN, removed_at=now - 1)

    result = event_history_admin.overview()

    assert [item["control_uuid"] for item in result["sources"]] == [SOURCE[0]]
    assert result["visible_event_count"] == 1
    assert result["database_bytes"] > 0


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
    monkeypatch.setattr(event_history_admin, "_controls", lambda _config: ())
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
    visible = event_history_admin._controls(config_store.load())

    def change_endpoint(_config):
        config_store.save(replace(config_store.load(), loxone_endpoint="https://other.example"))
        return visible

    monkeypatch.setattr(event_history_admin, "_controls", change_endpoint)
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
