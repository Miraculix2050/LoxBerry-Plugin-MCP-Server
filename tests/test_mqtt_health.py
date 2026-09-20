from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

from mcpserver.config import PluginConfig
from mcpserver.mqtt_health import (
    LOXONE_EPOCH_OFFSET,
    MqttCredentialStore,
    MqttGateway,
    MqttHealthPublisher,
    clear_retained_topics,
    loxone_epoch_seconds,
    mqtt_cleanup_required,
    request_service_restart,
)


class _Client:
    def __init__(self, **kwargs: object) -> None:
        self.calls: list[tuple[object, ...]] = [("new", kwargs)]

    def username_pw_set(self, username: str, password: str) -> None:
        self.calls.append(("credentials", username, password))

    def reconnect_delay_set(self, **kwargs: object) -> None:
        self.calls.append(("backoff", kwargs))

    def tls_set(self) -> None:
        self.calls.append(("tls",))

    def will_set(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("will", *args, kwargs))

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        self.calls.append(("connect", host, port, keepalive))

    def loop_start(self) -> None:
        self.calls.append(("loop_start",))

    def publish(self, *args: object, **kwargs: object) -> _Publication:
        self.calls.append(("publish", *args, kwargs))
        return _Publication()

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def loop_stop(self) -> None:
        self.calls.append(("loop_stop",))


class _Publication:
    def __init__(self, *, published: bool = True) -> None:
        self.published = published

    def wait_for_publish(self, *, timeout: float) -> None:
        del timeout

    def is_published(self) -> bool:
        return self.published


class _CleanupClient(_Client):
    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        super().connect_async(host, port, keepalive)
        self.on_connect(self, None, None, 0)


class _UnacknowledgedCleanupClient(_CleanupClient):
    def publish(self, *args: object, **kwargs: object) -> _Publication:
        super().publish(*args, **kwargs)
        return _Publication(published=False)


def test_retained_cleanup_decision_ignores_credentials_at_the_same_destination() -> None:
    previous = PluginConfig(
        mqtt_enabled=True,
        mqtt_root_topic="old",
        mqtt_use_loxberry_gateway=False,
        mqtt_host="broker.example",
        mqtt_port=2883,
        mqtt_username="old-user",
    )

    assert mqtt_cleanup_required(previous, previous) is False
    assert mqtt_cleanup_required(previous, replace(previous, mqtt_username="new-user")) is False
    assert mqtt_cleanup_required(previous, replace(previous, mqtt_root_topic="new")) is True
    assert mqtt_cleanup_required(previous, replace(previous, mqtt_enabled=False)) is True
    assert mqtt_cleanup_required(previous, replace(previous, mqtt_host="other.example")) is True
    assert mqtt_cleanup_required(previous, replace(previous, mqtt_port=1883)) is True
    assert (
        mqtt_cleanup_required(previous, replace(previous, mqtt_use_loxberry_gateway=True)) is True
    )


def test_retained_cleanup_removes_only_plugin_topics_with_a_confirmed_connection() -> None:
    clients: list[_CleanupClient] = []

    assert clear_retained_topics(
        PluginConfig(
            mqtt_enabled=True,
            mqtt_root_topic="old",
            mqtt_use_loxberry_gateway=False,
            mqtt_host="broker.example",
        ),
        broker=MqttGateway("broker.example", 1883, "health", "secret"),
        client_factory=lambda **kwargs: clients.append(_CleanupClient(**kwargs)) or clients[-1],
    )

    calls = clients[0].calls
    assert ("new", {"client_id": "loxberry-mcp-retained-cleanup"}) in calls
    assert ("credentials", "health", "secret") in calls
    assert ("tls",) in calls
    assert ("connect", "broker.example", 1883, 60) in calls
    assert {
        call[1]
        for call in calls
        if call[0] == "publish" and call[2:] == (b"", {"qos": 1, "retain": True})
    } == {
        "old/health/heartbeat",
        "old/health/system_state",
        "old/health/substate",
        "old/emergency_stop/status",
    }
    assert ("disconnect",) in calls
    assert ("loop_stop",) in calls


def test_retained_cleanup_failure_is_non_throwing() -> None:
    assert not clear_retained_topics(
        PluginConfig(mqtt_enabled=True),
        broker=MqttGateway("broker", 1883, "health", "secret"),
        client_factory=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )


def test_retained_cleanup_rejects_an_unacknowledged_deletion() -> None:
    clients: list[_UnacknowledgedCleanupClient] = []

    assert not clear_retained_topics(
        PluginConfig(
            mqtt_enabled=True, mqtt_use_loxberry_gateway=False, mqtt_host="broker.example"
        ),
        broker=MqttGateway("broker.example", 1883, "health", "secret"),
        client_factory=lambda **kwargs: clients.append(_UnacknowledgedCleanupClient(**kwargs))
        or clients[-1],
    )
    assert len([call for call in clients[0].calls if call[0] == "publish"]) == 1


def test_gateway_uses_loxberry_general_json(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )

    assert MqttGateway.from_loxberry_home(tmp_path) == MqttGateway("broker", 1883, "user", "secret")
    assert MqttGateway.from_loxberry_home(tmp_path / "missing") is None


def test_custom_broker_password_is_encrypted_and_used_without_gateway(
    tmp_path: Path, monkeypatch
) -> None:
    key = tmp_path / "install.key"
    key.write_bytes(b"k" * 32)
    credentials = tmp_path / "mqtt-credentials.json.enc"
    MqttCredentialStore(credentials.resolve(), key.resolve()).save("custom-secret")
    monkeypatch.setenv("MCPSERVER_MQTT_CREDENTIALS", str(credentials.resolve()))
    monkeypatch.setenv("MCPSERVER_INSTALL_KEY", str(key.resolve()))
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(
            mqtt_enabled=True,
            mqtt_use_loxberry_gateway=False,
            mqtt_host="broker.example",
            mqtt_port=2883,
            mqtt_username="custom-user",
        ),
        home=tmp_path / "no-gateway",
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
    )

    async def exercise() -> None:
        await publisher.start()
        await publisher.close()

    asyncio.run(exercise())
    assert credentials.read_text(encoding="utf-8").find("custom-secret") == -1
    calls = [call for client in clients for call in client.calls]
    assert ("credentials", "custom-user", "custom-secret") in calls
    assert ("tls",) in calls
    assert ("connect", "broker.example", 2883, 60) in calls


def test_health_publishes_retained_start_and_shutdown_messages(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(mqtt_enabled=True),
        home=tmp_path,
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
        state_reader=lambda: ("active", "running"),
    )

    async def exercise() -> None:
        await publisher.start()
        clients[0].on_connect(clients[0])
        clients[1].on_connect(clients[1])
        clients[2].on_connect(clients[2])
        publisher.publish()
        await publisher.close()

    asyncio.run(exercise())
    calls = [call for client in clients for call in client.calls]
    assert ("will", "mcpserver/health/system_state", "unknown", {"qos": 1, "retain": True}) in calls
    assert ("will", "mcpserver/health/substate", "unknown", {"qos": 1, "retain": True}) in calls
    assert (
        "will",
        "mcpserver/emergency_stop/status",
        "unknown",
        {"qos": 1, "retain": True},
    ) in calls
    assert any(
        call[:2] == ("publish", "mcpserver/health/heartbeat") and call[-1]["retain"]
        for call in calls
    )
    assert any(call[:2] == ("publish", "mcpserver/health/system_state") for call in calls)
    assert (
        "publish",
        "mcpserver/health/system_state",
        "inactive",
        {"qos": 1, "retain": True},
    ) in calls
    assert ("publish", "mcpserver/health/substate", "dead", {"qos": 1, "retain": True}) in calls
    assert (
        "publish",
        "mcpserver/emergency_stop/status",
        "unknown",
        {"qos": 1, "retain": True},
    ) in calls


def test_health_waits_for_each_broker_connection_before_publishing(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(mqtt_enabled=True),
        home=tmp_path,
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
        state_reader=lambda: ("active", "running"),
    )

    async def exercise() -> None:
        await publisher.start()
        publisher.publish()
        assert not [call for client in clients for call in client.calls if call[0] == "publish"]
        clients[0].on_connect(clients[0])
        assert any(
            call[:2] == ("publish", "mcpserver/health/system_state") for call in clients[0].calls
        )
        assert not any(
            call[:2] == ("publish", "mcpserver/health/substate") for call in clients[1].calls
        )
        clients[1].on_connect(clients[1])
        assert any(
            call[:2] == ("publish", "mcpserver/health/substate") for call in clients[1].calls
        )
        assert not any(
            call[:2] == ("publish", "mcpserver/emergency_stop/status") for call in clients[2].calls
        )
        clients[2].on_connect(clients[2])
        assert (
            "publish",
            "mcpserver/emergency_stop/status",
            "not_configured",
            {"qos": 1, "retain": True},
        ) in clients[2].calls
        await publisher.close()

    asyncio.run(exercise())


def test_health_replaces_last_will_immediately_with_the_service_ready_state(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(mqtt_enabled=True),
        home=tmp_path,
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
        state_reader=lambda: ("unknown", "unknown"),
    )

    async def exercise() -> None:
        await publisher.start()
        clients[0].on_connect(clients[0])
        clients[1].on_connect(clients[1])
        clients[2].on_connect(clients[2])
        await publisher.close()

    asyncio.run(exercise())
    assert (
        "publish",
        "mcpserver/health/system_state",
        "active",
        {"qos": 1, "retain": True},
    ) in clients[0].calls
    assert (
        "publish",
        "mcpserver/health/substate",
        "running",
        {"qos": 1, "retain": True},
    ) in clients[1].calls


def test_health_publishes_restarting_for_an_admin_initiated_restart(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(mqtt_enabled=True),
        home=tmp_path,
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
    )

    async def exercise() -> None:
        await publisher.start()
        clients[0].on_connect(clients[0])
        clients[1].on_connect(clients[1])
        clients[2].on_connect(clients[2])
        request_service_restart()
        await publisher.close()

    asyncio.run(exercise())
    assert (
        "publish",
        "mcpserver/health/system_state",
        "restarting",
        {"qos": 1, "retain": True},
    ) in clients[0].calls
    assert (
        "publish",
        "mcpserver/health/substate",
        "restarting",
        {"qos": 1, "retain": True},
    ) in clients[1].calls


def test_emergency_stop_mqtt_state_is_explicit_and_reconnects_immediately(tmp_path: Path) -> None:
    path = tmp_path / "config" / "system"
    path.mkdir(parents=True)
    (path / "general.json").write_text(
        json.dumps(
            {
                "Mqtt": {
                    "Brokerhost": "broker",
                    "Brokerport": 1883,
                    "Brokeruser": "user",
                    "Brokerpass": "secret",
                }
            }
        ),
        encoding="utf-8",
    )
    clients: list[_Client] = []
    publisher = MqttHealthPublisher(
        PluginConfig(
            mqtt_enabled=True,
            emergency_stop_virtual_status_uuid="00112233-4455-6677-8899aabbccddeeff",
        ),
        home=tmp_path,
        client_factory=lambda **kwargs: clients.append(_Client(**kwargs)) or clients[-1],
        emergency_stop_reader=lambda: "enabled",
    )

    async def exercise() -> None:
        await publisher.start()
        clients[2].on_connect(clients[2])
        clients[2].on_disconnect(clients[2])
        publications_before = len([call for call in clients[2].calls if call[0] == "publish"])
        publisher.publish()
        assert (
            len([call for call in clients[2].calls if call[0] == "publish"]) == publications_before
        )
        clients[2].on_connect(clients[2])
        await publisher.close()

    asyncio.run(exercise())
    assert [client.calls[0] for client in clients] == [
        ("new", {"client_id": "loxberry-mcp-health-state"}),
        ("new", {"client_id": "loxberry-mcp-health-substate"}),
        ("new", {"client_id": "loxberry-mcp-emergency-stop"}),
    ]
    assert (
        "will",
        "mcpserver/emergency_stop/status",
        "unknown",
        {"qos": 1, "retain": True},
    ) in clients[2].calls
    assert (
        clients[2].calls.count(
            ("publish", "mcpserver/emergency_stop/status", "clear", {"qos": 1, "retain": True})
        )
        == 2
    )


def test_emergency_stop_mqtt_state_mapping() -> None:
    configured = PluginConfig(
        emergency_stop_virtual_status_uuid="00112233-4455-6677-8899aabbccddeeff"
    )
    for monitor_state, expected in {
        "enabled": "clear",
        "disabled": "active",
        "unknown": "unknown",
        "unexpected": "unknown",
    }.items():
        publisher = MqttHealthPublisher(
            configured,
            home=Path("."),
            emergency_stop_reader=lambda monitor_state=monitor_state: monitor_state,
        )
        assert publisher._emergency_stop_state() == expected

    assert (
        MqttHealthPublisher(
            PluginConfig(), home=Path("."), emergency_stop_reader=lambda: "enabled"
        )._emergency_stop_state()
        == "not_configured"
    )


def test_stale_mqtt_client_callback_does_not_change_current_connection_state(
    tmp_path: Path,
) -> None:
    publisher = MqttHealthPublisher(PluginConfig(), home=tmp_path)
    current = _Client()
    publisher._clients = [current]
    publisher._connected_clients.add(0)

    publisher._on_disconnect(0, _Client())

    assert publisher._connected_clients == {0}


def test_missing_gateway_schedules_a_bounded_retry(tmp_path: Path) -> None:
    publisher = MqttHealthPublisher(
        PluginConfig(mqtt_enabled=True),
        home=tmp_path / "missing-gateway",
    )

    async def exercise() -> None:
        await publisher.start()
        assert publisher._task is not None
        assert publisher._clients == []
        await publisher.close()

    asyncio.run(exercise())


def test_loxone_epoch_is_compact_seconds() -> None:
    assert loxone_epoch_seconds(float(LOXONE_EPOCH_OFFSET + 123)) == 123
