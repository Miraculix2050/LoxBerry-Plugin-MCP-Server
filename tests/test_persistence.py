from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcpserver import admin, config, event_history_admin, mqtt_health, persistence
from mcpserver.auth import loxone_store, remote_revocation
from mcpserver.auth import store as auth_store
from mcpserver.config import (
    AtomicConfigStore,
    ConfigPersistenceUncertain,
    PluginConfig,
)
from mcpserver.mqtt_health import MqttCredentialStore, MqttPersistenceUncertain


@pytest.mark.parametrize("failure", [None, "open", "fsync"])
def test_directory_sync_order_and_descriptor_cleanup(monkeypatch, tmp_path, failure):
    events = []

    def opening(path, flags):
        assert path == tmp_path
        events.append("open")
        if failure == "open":
            raise OSError("open failed")
        return 42

    def syncing(fd):
        assert fd == 42
        events.append("fsync")
        if failure == "fsync":
            raise OSError("sync failed")

    def closing(fd):
        assert fd == 42
        events.append("close")

    monkeypatch.setattr(
        persistence,
        "os",
        SimpleNamespace(
            name="posix", O_RDONLY=0, O_DIRECTORY=1, open=opening, fsync=syncing, close=closing
        ),
    )
    if failure:
        with pytest.raises(OSError):
            persistence.fsync_parent_directory(tmp_path / "target")
    else:
        persistence.fsync_parent_directory(tmp_path / "target")
    assert events == (["open"] if failure == "open" else ["open", "fsync", "close"])


def test_non_posix_directory_sync_is_explicit_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(persistence, "os", SimpleNamespace(name="nt"))
    persistence.fsync_parent_directory(tmp_path / "target")


@pytest.mark.parametrize("kind", ["auth", "token", "revocation"])
def test_existing_authoritative_stores_preserve_sync_and_error_type(tmp_path, monkeypatch, kind):
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    if kind == "auth":
        module = auth_store
        store = auth_store.AtomicJsonAuthStore(tmp_path / "auth.json")
        document = store.snapshot()
        write = store._write_unlocked
        error_type = auth_store.AuthStoreError
    elif kind == "token":
        module = loxone_store
        store = loxone_store.EncryptedLoxoneTokenStore(tmp_path / "token.json", key)
        document = store._read()
        write = store._write
        error_type = loxone_store.LoxoneTokenStoreError
    else:
        module = remote_revocation
        store = remote_revocation.RemoteRevocationState(tmp_path / "token.json")
        document = store._empty()
        write = store.write
        error_type = remote_revocation.RemoteRevocationStateError
    cause = OSError("directory sync failed")
    calls = []

    def sync(path):
        assert json.loads(path.read_text()) == document
        calls.append(path)
        raise cause

    monkeypatch.setattr(module, "fsync_parent_directory", sync)
    with pytest.raises(error_type) as captured:
        write(document)
    assert captured.value.__cause__ is cause
    assert calls == [store.path]
    assert store.path.exists()


@pytest.mark.parametrize("kind", ["config", "mqtt"])
@pytest.mark.parametrize("phase", ["file", "replace", "directory", "cleanup"])
def test_store_commit_failure_boundary(tmp_path, monkeypatch, kind, phase):
    path = tmp_path / "store.json"
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    if kind == "config":
        module = config
        store = AtomicConfigStore(path)
        previous = PluginConfig.defaults()
        candidate = replace(previous, mqtt_host="candidate.example")
        uncertain = ConfigPersistenceUncertain
    else:
        module = mqtt_health
        store = MqttCredentialStore(path, key)
        previous, candidate = "old-password", "new-password"
        uncertain = MqttPersistenceUncertain
    store.save(previous)
    old = path.read_bytes()
    cause = OSError("injected failure")

    def fail(*args, **kwargs):
        raise cause

    if phase in {"file", "cleanup"}:
        monkeypatch.setattr(module.os, "fsync", fail)
    elif phase == "replace":
        monkeypatch.setattr(module.os, "replace", fail)
    else:
        monkeypatch.setattr(module, "fsync_parent_directory", fail)
    if phase == "cleanup":
        monkeypatch.setattr(
            Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("cleanup"))
        )
    with pytest.raises(Exception) as captured:
        store.save(candidate)
    assert captured.value.__cause__ is cause
    assert isinstance(captured.value, uncertain) == (phase == "directory")
    assert path.read_bytes() != old if phase == "directory" else path.read_bytes() == old
    expected = candidate if phase == "directory" else previous
    loaded = store.load()
    if kind == "config":
        assert loaded.to_document() == expected.to_document()
    else:
        assert loaded == expected
    if phase != "cleanup":
        assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("kind", ["config", "mqtt"])
def test_save_orders_file_replace_directory(tmp_path, monkeypatch, kind):
    path = tmp_path / "store.json"
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    module = config if kind == "config" else mqtt_health
    store = AtomicConfigStore(path) if kind == "config" else MqttCredentialStore(path, key)
    events = []
    real_sync, real_replace = os.fsync, os.replace

    def sync(fd):
        events.append("file")
        real_sync(fd)

    def replace_file(source, target):
        events.append("replace")
        assert source.stat().st_mode & 0o777 == 0o600 or os.name == "nt"
        real_replace(source, target)

    def directory(target):
        assert target.exists()
        events.append("directory")

    monkeypatch.setattr(module.os, "fsync", sync)
    monkeypatch.setattr(module.os, "replace", replace_file)
    monkeypatch.setattr(module, "fsync_parent_directory", directory)
    store.save(PluginConfig.defaults() if kind == "config" else "password")
    assert events == ["file", "replace", "directory"]


def test_mqtt_delete_syncs_only_after_unlink_and_keeps_uncertain_removal(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    store = MqttCredentialStore(tmp_path / "mqtt.json", key)
    store.save("password")
    calls = []

    def sync(path):
        assert not path.exists()
        calls.append(path)
        raise OSError("directory failed")

    monkeypatch.setattr(mqtt_health, "fsync_parent_directory", sync)
    with pytest.raises(MqttPersistenceUncertain):
        store.delete()
    store.delete()
    assert calls == [store.path]
    assert store.load() is None


@pytest.mark.parametrize("failure_store", ["config", "mqtt"])
def test_admin_mqtt_uncertainty_does_not_compensate_or_restart(
    tmp_path, monkeypatch, failure_store
):
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    credentials = MqttCredentialStore(tmp_path / "mqtt.json", key)
    credentials.save("previous")
    store = AtomicConfigStore(tmp_path / "config.json")
    previous = PluginConfig.defaults()
    store.save(previous)
    monkeypatch.setattr(admin, "_config_store", lambda: store)
    monkeypatch.setattr(admin, "_service_active", lambda: True)
    monkeypatch.setattr(admin, "_restart_service", lambda: pytest.fail("unexpected restart"))
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.path))
    calls = []

    def sync(path):
        calls.append(path)
        raise OSError("sync failed")

    module = config if failure_store == "config" else mqtt_health
    monkeypatch.setattr(module, "fsync_parent_directory", sync)
    document = replace(previous, mqtt_username="updated").to_document()
    document["mqtt_password"] = "updated"
    with pytest.raises(persistence.PersistenceUncertain):
        admin._save_mqtt(document)
    assert credentials.load() == "updated"
    assert store.load().mqtt_username == (
        "updated" if failure_store == "config" else previous.mqtt_username
    )
    assert len(calls) == 1


def test_admin_boundary_preserves_error_envelope(monkeypatch):
    def fail(*args, **kwargs):
        raise ConfigPersistenceUncertain("internal details")

    monkeypatch.setattr(admin, "_dispatch", fail)
    with pytest.raises(admin.AdminError) as captured:
        admin.dispatch({"action": "save_mcp_config"})
    assert captured.value.code == "persistence_uncertain"
    assert "Reload" in str(captured.value)
    assert "internal details" not in str(captured.value)


def test_admin_uncertainty_is_localized_for_ajax_and_fallback():
    root = Path(__file__).resolve().parents[1]
    cgi = (root / "webfrontend/htmlauth/index.cgi").read_text()
    assert "persistence_uncertain => $L{'AJAX.PERSISTENCE_UNCERTAIN'}" in cgi
    assert "$notice_value eq 'persistence_uncertain' ? $L{'AJAX.PERSISTENCE_UNCERTAIN'}" in cgi
    for language in ("de", "en"):
        text = (root / f"templates/lang/language_{language}.ini").read_text()
        assert "PERSISTENCE_UNCERTAIN=" in text


@pytest.mark.parametrize("capability", ["read", "operate"])
def test_explorer_approval_does_not_reclassify_persistence_uncertainty(monkeypatch, capability):
    record = {
        "expires_at": 4_000_000_000,
        "client_kind": "tool_explorer",
        "pending_loxberry_read": True,
        "pending_loxberry_operate": True,
        "scope": "loxone:read loxone:history loxberry:operate",
    }
    monkeypatch.setattr(
        admin,
        "_auth_store",
        lambda: SimpleNamespace(snapshot=lambda: {"families": {"session": record}}),
    )
    monkeypatch.setattr(admin, "_config_store", lambda: None)

    def fail(*args, **kwargs):
        raise ConfigPersistenceUncertain("visible approval")

    monkeypatch.setattr("mcpserver.explorer_bindings.record_explorer_approval", fail)
    with pytest.raises(ConfigPersistenceUncertain):
        getattr(admin, f"_allow_loxberry_{capability}")({"session_id": "session"})


def test_event_history_uncertain_rollback_reports_failed_rollback(monkeypatch):
    previous = PluginConfig.defaults()
    writes, restarts = [], []

    def save(candidate):
        writes.append(candidate)
        if len(writes) == 2:
            raise ConfigPersistenceUncertain("rollback visible")

    def restart():
        restarts.append(True)
        raise admin.AdminError("apply failed")

    store = SimpleNamespace(transaction=lambda apply: apply(previous, save))
    bridge = SimpleNamespace(
        _config_store=lambda: store,
        _service_active=lambda: True,
        _restart_service=restart,
        AdminError=admin.AdminError,
    )
    monkeypatch.setattr(event_history_admin, "_bridge", lambda: bridge)
    with pytest.raises(admin.AdminError, match="apply and rollback failed") as captured:
        event_history_admin._apply(lambda current: replace(current, event_history_enabled=True))
    assert captured.value.code == "outcome_unknown"
    assert isinstance(captured.value.__cause__, ConfigPersistenceUncertain)
    assert len(writes) == 2 and len(restarts) == 1


def test_mqtt_uncertain_rollback_stops_further_compensation(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_bytes(b"k" * 32)
    credentials = MqttCredentialStore(tmp_path / "mqtt.json", key)
    credentials.save("previous")
    store = AtomicConfigStore(tmp_path / "config.json")
    previous = PluginConfig.defaults()
    store.save(previous)
    monkeypatch.setattr(admin, "_config_store", lambda: store)
    monkeypatch.setattr(admin, "_service_active", lambda: True)
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key))
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.path))
    syncs, restarts = [], []

    def sync(path):
        syncs.append(path)
        if len(syncs) == 2:
            raise OSError("rollback directory sync failed")

    def restart():
        restarts.append(True)
        raise admin.AdminError("apply failed")

    monkeypatch.setattr(config, "fsync_parent_directory", sync)
    monkeypatch.setattr(admin, "_restart_service", restart)
    document = previous.to_document()
    document["mqtt_password"] = "updated"
    with pytest.raises(admin.AdminError, match="apply and rollback failed") as captured:
        admin._save_mqtt(document)
    assert isinstance(captured.value.__cause__, ConfigPersistenceUncertain)
    assert credentials.load() == "updated"
    assert store.load().to_document() == previous.to_document()
    assert len(syncs) == 2 and len(restarts) == 1


@pytest.mark.parametrize("fail_sync", [False, True])
def test_upgrade_migration_sync_failure_and_idempotency(tmp_path, monkeypatch, fail_sync):
    hook = (Path(__file__).resolve().parents[1] / "postupgrade.sh").read_text()
    code = hook.split("python3 - \"$plugin_config/mcpserver.json\" <<'PY' || exit 2\n", 1)[1].split(
        "\nPY", 1
    )[0]
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 10}))
    events = []
    real_replace = os.replace

    def replacing(source, target):
        events.append("replace")
        real_replace(source, target)

    # Execute the standalone migration with an os proxy, including on Windows.
    real_import = __import__
    proxy = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
    proxy.O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
    real_open = os.open
    proxy.open = lambda p, flags, *a, **k: 4242 if p == tmp_path else real_open(p, flags, *a, **k)
    proxy.replace = replacing

    def syncing(fd):
        events.append("directory" if fd == 4242 else "file")
        if fd == 4242 and fail_sync:
            raise OSError("directory failed")

    proxy.fsync = syncing
    proxy.close = lambda fd: events.append("close") if fd == 4242 else os.close(fd)

    def importing(name, *args, **kwargs):
        return proxy if name == "os" else real_import(name, *args, **kwargs)

    monkeypatch.setattr("sys.argv", ["migration", str(path)])
    namespace = {"__builtins__": {**vars(__import__("builtins")), "__import__": importing}}
    if fail_sync:
        with pytest.raises(OSError, match="directory failed"):
            exec(code, namespace)
    else:
        exec(code, namespace)
    assert events == ["file", "replace", "directory", "close"]
    assert json.loads(path.read_text())["schema_version"] == 11
    events.clear()
    if fail_sync:
        with pytest.raises(OSError, match="directory failed"):
            exec(code, namespace)
        assert events == ["directory", "close"]
        fail_sync = False
        events.clear()
    exec(code, namespace)
    assert events == ["directory", "close"]
    assert not list(tmp_path.glob("*.tmp"))
