from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcpserver.config import PluginConfig
from mcpserver.mqtt_health import (
    LOXONE_EPOCH_OFFSET,
    MqttCredentialStore,
    MqttGateway,
    MqttHealthPublisher,
    loxone_epoch_seconds,
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

    def publish(self, *args: object, **kwargs: object) -> None:
        self.calls.append(("publish", *args, kwargs))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def loop_stop(self) -> None:
        self.calls.append(("loop_stop",))


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
        publisher.publish()
        await publisher.close()

    asyncio.run(exercise())
    calls = [call for client in clients for call in client.calls]
    assert ("will", "mcpserver/health/system_state", "unknown", {"qos": 1, "retain": True}) in calls
    assert ("will", "mcpserver/health/substate", "unknown", {"qos": 1, "retain": True}) in calls
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
