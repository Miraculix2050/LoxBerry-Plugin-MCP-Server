"""Measure deterministic admin page-state aggregation with synthetic sessions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import statistics
import time
import tracemalloc
from dataclasses import replace
from typing import Any
from unittest.mock import patch

from mcpserver import admin
from mcpserver.auth.provider import (
    HISTORY_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
    LOXBERRY_READ_SCOPE,
    READ_SCOPE,
)
from mcpserver.config import PluginConfig


def _binding(subject_key: bytes, namespace: str, record: dict[str, Any]) -> str:
    canonical = "\0".join(
        (
            namespace,
            str(record["client_id"]),
            str(record["identity_id"]),
            str(record["miniserver_id"]),
        )
    ).encode("utf-8")
    return hmac.new(subject_key, canonical, hashlib.sha256).hexdigest()


def _fixture(session_count: int) -> tuple[PluginConfig, dict[str, Any]]:
    subject_key = b"b" * 32
    families = {
        f"benchmark-{index:04}": {
            "scope": f"{READ_SCOPE} {HISTORY_SCOPE} {LOXBERRY_READ_SCOPE} {LOXBERRY_OPERATE_SCOPE}",
            "client_id": f"client-{index}",
            "identity_id": f"identity-{index}",
            "miniserver_id": "benchmark-miniserver",
            "expires_at": 2_000_000_000,
            "pending_loxberry_read": True,
            "pending_loxberry_operate": True,
            "revoked": False,
        }
        for index in range(session_count)
    }
    first = next(iter(families.values()), {"client_id": "", "identity_id": "", "miniserver_id": ""})
    configuration = replace(
        PluginConfig.defaults(),
        loxberry_read_bindings=(_binding(subject_key, "loxberry-read-binding-v1", first),),
        loxberry_operate_bindings=(_binding(subject_key, "loxberry-operate-binding-v1", first),),
    )
    return configuration, {
        "schema_version": 1,
        "subject_key": base64.urlsafe_b64encode(subject_key).decode("ascii"),
        "clients": {},
        "families": families,
        "codes": {},
        "access_tokens": {},
        "refresh_tokens": {},
    }


class _ConfigStore:
    def __init__(self, configuration: PluginConfig) -> None:
        self.configuration = configuration

    def load(self) -> PluginConfig:
        return self.configuration


class _AuthStore:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def snapshot(self) -> dict[str, Any]:
        return self.document


def _percentile(values: list[float], percent: float) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[percent - 1]


def measure(*, session_count: int, warmups: int, samples: int) -> dict[str, int | float]:
    configuration, document = _fixture(session_count)
    with (
        patch.object(admin, "_config_store", lambda: _ConfigStore(configuration)),
        patch.object(admin, "_auth_store", lambda: _AuthStore(document)),
        patch.object(admin, "_service_status", lambda: {"active": True}),
        patch.object(admin, "_certificate_status", lambda **_kwargs: {"available": False}),
    ):
        for _ in range(warmups):
            admin.dispatch({"action": "page_state"})
        durations: list[float] = []
        tracemalloc.start()
        for _ in range(samples):
            start = time.perf_counter()
            admin.dispatch({"action": "page_state"})
            durations.append((time.perf_counter() - start) * 1000)
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return {
        "sessions": session_count,
        "warmups": warmups,
        "samples": samples,
        "p50_ms": round(statistics.median(durations), 3),
        "p95_ms": round(_percentile(durations, 95), 3),
        "peak_bytes": peak_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=100)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--samples", type=int, default=30)
    arguments = parser.parse_args()
    if arguments.sessions < 1 or arguments.warmups < 0 or arguments.samples < 2:
        parser.error("sessions must be positive, warmups non-negative, and samples at least two")
    print(json.dumps(measure(session_count=arguments.sessions, warmups=arguments.warmups, samples=arguments.samples)))


if __name__ == "__main__":
    main()
