"""Independent retained MQTT health publisher for the local LoxBerry gateway."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
import stat
import subprocess
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mcpserver.config import PluginConfig

LOXONE_EPOCH_OFFSET: Final = 1_230_768_000
_LOGGER = logging.getLogger("mcpserver.mqtt_health")
_CREDENTIALS_AAD: Final = b"mcpserver:mqtt-credentials:v1"


class MqttCredentialStoreError(RuntimeError):
    """Custom MQTT credentials cannot be handled safely."""


class MqttCredentialStore:
    """Small encrypted store for the optional custom MQTT broker password."""

    def __init__(self, path: Path, key_path: Path) -> None:
        if not path.is_absolute() or not key_path.is_absolute():
            raise ValueError("MQTT credential paths must be absolute")
        self.path = path
        self.key_path = key_path

    def _key(self) -> bytes:
        try:
            metadata = self.key_path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.key_path.is_symlink():
                raise MqttCredentialStoreError("MQTT installation key is unsafe")
            key = self.key_path.read_bytes()
        except MqttCredentialStoreError:
            raise
        except OSError as exc:
            raise MqttCredentialStoreError("MQTT installation key is unavailable") from exc
        if len(key) != 32:
            raise MqttCredentialStoreError("MQTT installation key is invalid")
        return key

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            metadata = self.path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or self.path.is_symlink():
                raise MqttCredentialStoreError("MQTT credential path is unsafe")
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or set(document) != {
                "schema_version",
                "nonce",
                "ciphertext",
            }:
                raise MqttCredentialStoreError("MQTT credential store is invalid")
            if document.get("schema_version") != 1:
                raise MqttCredentialStoreError("MQTT credential store is invalid")
            nonce = base64.urlsafe_b64decode(str(document["nonce"]).encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(str(document["ciphertext"]).encode("ascii"))
            password = (
                AESGCM(self._key()).decrypt(nonce, ciphertext, _CREDENTIALS_AAD).decode("utf-8")
            )
            if len(password) > 1024:
                raise MqttCredentialStoreError("MQTT password is invalid")
            return password
        except MqttCredentialStoreError:
            raise
        except (OSError, UnicodeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise MqttCredentialStoreError("MQTT credential store is unreadable") from exc
        except Exception as exc:
            raise MqttCredentialStoreError("MQTT credential store cannot be decrypted") from exc

    def save(self, password: str) -> None:
        if not isinstance(password, str) or len(password) > 1024 or "\x00" in password:
            raise MqttCredentialStoreError("MQTT password is invalid")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._key()).encrypt(nonce, password.encode("utf-8"), _CREDENTIALS_AAD)
        document = {
            "schema_version": 1,
            "nonce": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode("ascii"),
        }
        temporary = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    document, handle, ensure_ascii=True, separators=(",", ":"), sort_keys=True
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise MqttCredentialStoreError("MQTT credential store update failed") from exc


@dataclass(frozen=True, slots=True)
class MqttGateway:
    """Non-persistent broker settings supplied by LoxBerry's MQTT gateway."""

    host: str
    port: int
    username: str
    password: str

    @classmethod
    def from_loxberry_home(cls, home: Path) -> MqttGateway | None:
        path = home / "config" / "system" / "general.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            mqtt = document.get("Mqtt")
            if not isinstance(mqtt, dict):
                return None
            host = mqtt.get("Brokerhost")
            port_value = mqtt.get("Brokerport")
            username = mqtt.get("Brokeruser")
            password = mqtt.get("Brokerpass")
            if (
                not isinstance(host, str)
                or not host.strip()
                or not isinstance(port_value, int | str)
                or not isinstance(username, str)
                or not isinstance(password, str)
            ):
                return None
            if isinstance(port_value, bool) or not str(port_value).isdecimal():
                return None
            port = int(port_value)
            if not 1 <= port <= 65535:
                return None
            return cls(host=host.strip(), port=port, username=username, password=password)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None


def loxone_epoch_seconds(now: float | None = None) -> int:
    return int(time.time() if now is None else now) - LOXONE_EPOCH_OFFSET


def service_state() -> tuple[str, str]:
    """Read only the local unit state; failures are deliberately non-fatal."""
    try:
        result = subprocess.run(
            [
                "/bin/systemctl",
                "show",
                "--property=ActiveState",
                "--property=SubState",
                "--value",
                "loxberry-mcpserver.service",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        values = result.stdout.splitlines()
        if result.returncode == 0 and len(values) >= 2:
            return values[0] or "unknown", values[1] or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown", "unknown"


class MqttHealthPublisher:
    """Publish retained health without coupling MQTT availability to MCP."""

    def __init__(
        self,
        config: PluginConfig,
        *,
        home: Path,
        client_factory: Callable[..., Any] | None = None,
        state_reader: Callable[[], tuple[str, str]] = service_state,
    ) -> None:
        self._config = config
        self._home = home
        self._client_factory = client_factory
        self._state_reader = state_reader
        self._clients: list[Any] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def topics(self) -> dict[str, str]:
        prefix = self._config.mqtt_root_topic
        return {
            "heartbeat": f"{prefix}/health/heartbeat",
            "system_state": f"{prefix}/health/system_state",
            "substate": f"{prefix}/health/substate",
        }

    async def start(self) -> None:
        if not self._config.mqtt_enabled:
            return
        gateway = self._broker()
        if gateway is None:
            _LOGGER.warning("event=mqtt_broker_unavailable")
            return
        try:
            self._clients = self._create_clients(gateway)
            for client in self._clients:
                client.connect_async(gateway.host, gateway.port, keepalive=60)
                client.loop_start()
            self.publish()
            self._task = asyncio.create_task(self._publish_loop())
        except Exception:
            self._close_clients()
            _LOGGER.warning("event=mqtt_connect_failed")

    def _broker(self) -> MqttGateway | None:
        if self._config.mqtt_use_loxberry_gateway:
            return MqttGateway.from_loxberry_home(self._home)
        path_value = os.getenv("MCPSERVER_MQTT_CREDENTIALS", "").strip()
        key_value = os.getenv("MCPSERVER_INSTALL_KEY", "").strip()
        password = ""
        if path_value and key_value:
            try:
                password = MqttCredentialStore(Path(path_value), Path(key_value)).load() or ""
            except MqttCredentialStoreError:
                _LOGGER.warning("event=mqtt_credentials_unavailable")
                return None
        return MqttGateway(
            host=self._config.mqtt_host,
            port=self._config.mqtt_port,
            username=self._config.mqtt_username,
            password=password,
        )

    def _create_clients(self, gateway: MqttGateway) -> list[Any]:
        if self._client_factory is None:
            import paho.mqtt.client as paho  # type: ignore[import-not-found, import-untyped]

            factory: Callable[..., Any] = paho.Client
        else:
            factory = self._client_factory
        topics = self.topics
        # MQTT permits one Last-Will per connection. Two connections preserve the
        # requested independent retained unknown values for abrupt termination.
        clients = [
            factory(client_id="loxberry-mcp-health-state"),
            factory(client_id="loxberry-mcp-health-substate"),
        ]
        for client in clients:
            client.username_pw_set(gateway.username, gateway.password)
            client.reconnect_delay_set(min_delay=1, max_delay=60)
        clients[0].will_set(topics["system_state"], "unknown", qos=1, retain=True)
        clients[1].will_set(topics["substate"], "unknown", qos=1, retain=True)
        return clients

    async def _publish_loop(self) -> None:
        try:
            while True:
                self.publish()
                await asyncio.sleep(self._config.mqtt_heartbeat_seconds)
        except asyncio.CancelledError:
            raise

    def publish(self) -> None:
        if not self._clients:
            return
        active_state, substate = self._state_reader()
        topics = self.topics
        try:
            self._clients[0].publish(
                topics["heartbeat"], str(loxone_epoch_seconds()), qos=1, retain=True
            )
            self._clients[0].publish(topics["system_state"], active_state, qos=1, retain=True)
            self._clients[1].publish(topics["substate"], substate, qos=1, retain=True)
        except Exception:
            _LOGGER.warning("event=mqtt_publish_failed")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        topics = self.topics
        try:
            if self._clients:
                self._clients[0].publish(topics["system_state"], "inactive", qos=1, retain=True)
                self._clients[1].publish(topics["substate"], "dead", qos=1, retain=True)
        except Exception:
            _LOGGER.warning("event=mqtt_shutdown_publish_failed")
        self._close_clients()

    def _close_clients(self) -> None:
        for client in self._clients:
            try:
                client.disconnect()
                client.loop_stop()
            except Exception:
                pass
        self._clients = []
