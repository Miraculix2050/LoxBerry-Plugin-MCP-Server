import asyncio
import json
import sqlite3
import time
from dataclasses import replace

import pytest

from mcpserver.config import ConfigError, PluginConfig
from mcpserver.loxone.event_history import EventHistoryStore, _solar_sampling_stream
from mcpserver.loxone.models import Control
from mcpserver.solar_recording import (
    SolarHistory,
    SolarRecordingSource,
    SolarSampler,
    parse_sources,
)

C = "12345678-1234-1234-1234567890123456"
S = "12345678-1234-1234-1234567890123457"


def source(**values):
    return SolarRecordingSource.model_validate(
        dict(
            control_uuid=C,
            state_uuid=S,
            kind="irradiance",
            unit="W/m²",
            source_reference="documented independent local observation",
            confirmed=True,
        )
        | values
    )


def control():
    return Control(
        C,
        "independent observation",
        "InfoOnlyAnalog",
        None,
        None,
        None,
        (("value", S),),
        format="%.1fW/m²",
    )


def test_configuration_is_opt_in_and_preserves_unknown_fields():
    base = PluginConfig.defaults()
    assert not base.solar_history_enabled and not base.solar_history_sources
    document = replace(
        base,
        loxone_history_enabled=True,
        solar_history_enabled=True,
        solar_history_sources=(source(),),
    ).to_document()
    document["event_history"]["unrelated"] = "preserved"
    parsed = PluginConfig.from_document(document)
    assert parsed.solar_history_enabled and parsed.solar_history_sources == (source(),)
    assert parsed.to_document()["event_history"]["unrelated"] == "preserved"
    document["tools"]["loxone_history_enabled"] = False
    with pytest.raises(ConfigError):
        PluginConfig.from_document(document)


@pytest.mark.parametrize(
    "update",
    [
        dict(unit="lux"),
        dict(confirmed=False),
        dict(source_reference=""),
        dict(sampling_period_seconds=1),
        dict(kind="forecast"),
        dict(state_uuid=None),
        dict(source_reference="line\nbreak"),
    ],
)
def test_invalid_source_contracts_are_rejected(update):
    with pytest.raises(ValueError):
        source(**update)


def test_duplicate_sources_and_changed_identity():
    s = source()
    with pytest.raises(ValueError):
        parse_sources([s.model_dump(), s.model_dump()])
    fingerprint = s.fingerprint(control(), "plant")
    assert fingerprint != s.fingerprint(control(), "other plant")
    assert fingerprint != s.fingerprint(replace(control(), format="%.2fW/m²"), "plant")
    with pytest.raises(ValueError):
        s.fingerprint(replace(control(), is_hidden=True), "plant")


def test_sampler_records_current_unchanged_values_without_extra_source_reads():
    sampler = SolarSampler((source(),), (control(),), "plant")
    assert sampler.batch({}, 0) == []
    first = sampler.batch({S: 100, "unselected": "private"}, 1)
    assert len(first) == 1 and json.loads(first[0][3])["value"] == 100
    assert sampler.batch({}, 30) == []
    assert len(sampler.batch({}, 61)) == 1
    assert "unselected" not in sampler.values
    # A new stream cannot continue a stale cache across a disconnect.
    assert SolarSampler((source(),), (control(),), "plant").batch({}, 121) == []


def test_metadata_revalidation_keeps_only_unchanged_visible_source_values():
    sampler = SolarSampler((source(),), (control(),), "plant")
    sampler.batch({S: 100}, 1)
    unchanged = sampler.revalidated((control(),), "plant")
    assert len(unchanged.batch({}, 61)) == 1
    changed = unchanged.revalidated((replace(control(), format="%.2fW/m²"),), "plant")
    assert changed.batch({}, 121) == []
    assert len(changed.batch({S: 200}, 122)) == 1
    hidden = changed.revalidated((replace(control(), is_hidden=True),), "plant")
    assert not hidden.sources and not hidden.values
    assert hidden.batch({S: 300}, 182) == []
    restored = hidden.revalidated((control(),), "plant")
    assert restored.sources and restored.batch({}, 242) == []
    assert len(restored.batch({S: 300}, 243)) == 1
    assert restored.revalidated((control(),), "other plant").batch({}, 303) == []


def test_pvpf_snapshots_are_complete_and_settled():
    from mcpserver.loxone.pv_forecast import STATES

    names = sorted(STATES)
    refs = tuple((name, f"state-{name}") for name in names)
    c = replace(control(), control_type="PvProductionForecast", state_uuids=refs)
    s = source(kind="pv_forecast", state_uuid=None, unit="kWh")
    sampler = SolarSampler((s,), (c,), "plant")
    values = {f"state-{name}": 0 for name in names}
    values.update(
        {
            "state-period": -1,
            "state-today": -1,
            "state-tomorrow": -1,
            "state-after": -1,
            "state-errorInfo": 2,
        }
    )
    assert sampler.batch(values, 1) == []
    rows = sampler.batch({}, 3)
    assert len(rows) == 1
    assert json.loads(rows[0][3])["value_origin"] == "forecast"
    assert sampler.batch({}, 10) == []
    assert sampler.batch({}, 63) == []
    assert sampler.batch({"state-inputperiod": 1}, 64) == []
    assert len(sampler.batch({}, 124)) == 1


def test_incomplete_pvpf_cannot_be_registered_for_complete_snapshots():
    c = replace(control(), control_type="PvProductionForecast", state_uuids=(("ready", S),))
    s = source(kind="pv_forecast", state_uuid=None, unit="kWh")
    with pytest.raises(ValueError, match="unsupported_pv_forecast"):
        s.fingerprint(c, "plant")
    assert not SolarSampler((s,), (c,), "plant").sources


@pytest.mark.parametrize("oldest", ["weather", "scalar"])
def test_shared_size_eviction_does_not_cross_an_older_dataset(tmp_path, oldest):
    from test_weather_history import SOURCE, delivery

    from mcpserver.loxone.weather_history import WeatherHistory

    store = EventHistoryStore(tmp_path / "history.sqlite3", retention_days=7, maximum_mib=16)
    store.initialize()
    base = time.time() - 1000
    weather = WeatherHistory(store)
    capture = weather.begin(SOURCE, "fixture", base)
    # The first large prefix can free pages on its own. Newer rows in that
    # dataset must remain when an older row belongs to a different dataset.
    for i in range(7):
        at = base + (10 + i if oldest == "weather" and i < 3 else 50 + i)
        weather.record(capture, SOURCE, delivery(base + 3600 + i, value=i, count=96), at)
    for i in range(7):
        at = base + (10 + i if oldest == "scalar" and i < 3 else 80 + i)
        store.record_transition(C, S, observed_at=at, old_value="a" * 2000, new_value="b" * 2000)
    s = source()
    SolarHistory(store).record([(s.key, "fingerprint", base + 40, '{"value":100}')])
    with store._opened() as db:
        store.maximum_bytes = store._used_database_bytes(db) - 4096
        db.execute("BEGIN IMMEDIATE")
        assert store._prune(db, now=time.time())
        db.execute("COMMIT")
        if oldest == "weather":
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM weather_deliveries WHERE received_at>=?", (base + 50,)
                ).fetchone()[0]
                == 4
            )
        else:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM events WHERE observed_at>=?", (base + 80,)
                ).fetchone()[0]
                == 4
            )


def test_shared_store_migration_retention_index_and_budget(tmp_path):
    path = tmp_path / "events.sqlite3"
    store = EventHistoryStore(path, retention_days=7, maximum_mib=16)
    store.initialize()
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE solar_samples")
        db.execute("PRAGMA user_version=8")
    store.prepare_chart_read()
    s = source()
    fingerprint = s.fingerprint(control(), "plant")
    now = time.time()
    history = SolarHistory(store)
    history.record([(s.key, fingerprint, now - 1, '{"value":100}')])
    rows, count = history.read(
        s, fingerprint, now - 60, now, maximum_points=10, deadline=time.monotonic() + 5
    )
    assert count == 1 and rows[0][1]["value"] == 100
    assert history.read(
        s, "changed", now - 60, now, maximum_points=10, deadline=time.monotonic() + 5
    ) == ([], 0)
    with pytest.raises(ValueError, match="limit"):
        history.read(s, fingerprint, now - 60, now, maximum_points=0, deadline=time.monotonic() + 5)
    with sqlite3.connect(path) as db:
        query = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM solar_samples WHERE "
            "source_key=? AND fingerprint=? AND observed_at>=? AND observed_at<? "
            "ORDER BY observed_at,id LIMIT 10",
            (s.key, fingerprint, now - 60, now),
        ).fetchall()
        assert any("solar_samples_source_time" in row[3] for row in query)
        db.execute("UPDATE solar_samples SET observed_at=?", (now - 8 * 86400,))
    store.initialize()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM solar_samples").fetchone()[0] == 0
        assert db.execute("PRAGMA user_version").fetchone()[0] == 9


@pytest.mark.asyncio
async def test_sampling_stream_has_one_reader_and_closes_on_cancellation():
    active = False
    closed = False

    async def stream():
        nonlocal active, closed
        try:
            assert not active
            active = True
            await asyncio.sleep(10)
            yield ()
        finally:
            closed = True

    wrapper = _solar_sampling_stream(stream(), 0.01)
    for _ in range(3):
        assert await anext(wrapper) == ()
        assert not closed
    await wrapper.aclose()
    assert closed


def test_local_admin_source_policy_preserves_other_fields_and_rejects_stale_edits(
    tmp_path, monkeypatch
):
    from mcpserver import admin, event_history_admin
    from mcpserver.config import AtomicConfigStore
    from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure

    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(PluginConfig(loxone_endpoint="http://192.168.10.20", loxone_history_enabled=True))
    structure = LoxoneStructure(LoxoneIdentity("service", "serial"), "17.2", (), (), (control(),))
    monkeypatch.setattr(admin, "_config_store", lambda: store)
    monkeypatch.setattr(admin, "_service_active", lambda: False)
    monkeypatch.setattr(event_history_admin, "_weather_structure", lambda cfg: structure)
    options = event_history_admin.solar_sources("solar_history_options", {"discover": True})
    assert options["choices"][0]["kind"] == "irradiance"
    payload = dict(
        sources=[source().model_dump()], enabled=True, revision=options["revision"], confirm=True
    )
    with pytest.raises(admin.AdminError, match="confirmation"):
        event_history_admin.solar_sources("solar_history_save", payload | {"confirm": False})
    saved = event_history_admin.solar_sources("solar_history_save", payload)
    assert saved["changed"] and store.load().solar_history_enabled
    assert store.load().loxone_endpoint == "http://192.168.10.20"
    with pytest.raises(admin.AdminError, match="changed"):
        event_history_admin.solar_sources("solar_history_save", payload | {"enabled": False})


def test_offline_local_configuration_can_be_disabled_and_cleared(tmp_path, monkeypatch):
    from mcpserver import admin, event_history_admin
    from mcpserver.config import AtomicConfigStore

    store = AtomicConfigStore(tmp_path / "config.json")
    store.save(
        PluginConfig(
            loxone_endpoint="http://192.168.10.20",
            loxone_history_enabled=True,
            solar_history_enabled=True,
            solar_history_sources=(source(),),
        )
    )
    monkeypatch.setattr(admin, "_config_store", lambda: store)
    monkeypatch.setattr(admin, "_service_active", lambda: False)

    def offline(_config):
        raise admin.AdminError("offline", code="temporarily_unavailable")

    monkeypatch.setattr(event_history_admin, "_weather_structure", offline)
    local = event_history_admin.solar_sources("solar_history_options", {})
    assert local["enabled"] and len(local["sources"]) == 1 and local["choices"] == []
    with pytest.raises(admin.AdminError, match="offline"):
        event_history_admin.solar_sources("solar_history_options", {"discover": True})
    saved = event_history_admin.solar_sources(
        "solar_history_save",
        dict(enabled=False, sources=[], revision=local["revision"], confirm=True),
    )
    assert not saved["enabled"] and not store.load().solar_history_sources
    with pytest.raises(admin.AdminError, match="offline"):
        event_history_admin.solar_sources(
            "solar_history_save",
            dict(
                enabled=True,
                sources=[source().model_dump()],
                revision=saved["revision"],
                confirm=True,
            ),
        )


@pytest.mark.parametrize("active", [False, True])
def test_main_form_rejects_revoking_history_with_preserved_solar_policy(
    tmp_path, monkeypatch, active
):
    from mcpserver import admin
    from mcpserver.config import AtomicConfigStore

    store = AtomicConfigStore(tmp_path / "config.json")
    previous = PluginConfig(
        loxone_history_enabled=True, solar_history_enabled=True, solar_history_sources=(source(),)
    )
    store.save(previous)
    monkeypatch.setattr(admin, "_config_store", lambda: store)
    monkeypatch.setattr(admin, "_service_active", lambda: active)
    monkeypatch.setattr(admin, "_restart_service", lambda: pytest.fail("invalid policy restarted"))
    with pytest.raises(ConfigError, match="solar"):
        admin._save_mcp({"schema_version": 10, "tools": {"loxone_history_enabled": False}})
    assert store.load().to_document() == previous.to_document()


@pytest.mark.asyncio
async def test_solar_metadata_failure_pauses_only_solar_and_can_recover(tmp_path, monkeypatch):
    from mcpserver.installation_profile import installation_identity
    from mcpserver.loxone.event_history import EventHistoryMonitor
    from mcpserver.loxone.models import LoxoneIdentity, LoxoneStructure

    structure = LoxoneStructure(LoxoneIdentity("service", "serial"), "17.2", (), (), (control(),))
    origin = "http://192.168.10.20"
    sampler = SolarSampler((source(),), (control(),), installation_identity(origin, structure))
    sampler.batch({S: 100}, 100)
    monitor = EventHistoryMonitor(
        PluginConfig(loxone_endpoint=origin),
        EventHistoryStore(tmp_path / "s.sqlite3", retention_days=7, maximum_mib=16),
        object(),
    )

    async def unavailable():
        raise TimeoutError("private upstream message")

    monkeypatch.setattr(monitor, "visible_structure", unavailable)
    paused = await monitor._refresh_solar_sampler(sampler)
    assert not paused.sources and not paused.values
    assert paused.configured_sources == sampler.configured_sources

    async def available():
        return structure

    monkeypatch.setattr(monitor, "visible_structure", available)
    restored = await monitor._refresh_solar_sampler(paused)
    assert restored.sources and not restored.values
    assert restored.batch({S: 150}, 200)

    async def cancelled():
        raise asyncio.CancelledError

    monkeypatch.setattr(monitor, "visible_structure", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await monitor._refresh_solar_sampler(restored)
