from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.explorer_bindings import (
    active_explorer_binding,
    explorer_binding_id,
    maintain_explorer_bindings,
    record_explorer_approval,
)

EXPLORER_ORIGIN = "https://public.example"


def stores(tmp_path: Path) -> tuple[AtomicConfigStore, AtomicJsonAuthStore]:
    config_store = AtomicConfigStore((tmp_path / "config.json").resolve())
    config_store.save(PluginConfig.defaults())
    auth_store = AtomicJsonAuthStore((tmp_path / "sessions.json").resolve())
    return config_store, auth_store


def family(
    *,
    client_id: str = "explorer-a",
    identity: str = "identity-a",
    miniserver: str = "ms-a",
) -> dict[str, object]:
    return {
        "client_id": client_id,
        "client_kind": "tool_explorer",
        "explorer_origin": EXPLORER_ORIGIN,
        "identity_id": identity,
        "miniserver_id": miniserver,
        "scope": "loxone:read loxberry:read",
        "created_at": 100,
        "expires_at": 200,
        "revoked": False,
    }


def test_new_explorer_client_instance_reuses_same_application_binding(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    first = family(client_id="first-client")
    second = family(client_id="second-client")

    first_id = record_explorer_approval(config_store, auth_store, "loxberry:read", first, now=100)
    assert (
        active_explorer_binding(
            config_store.load(),
            auth_store,
            "loxberry:read",
            "identity-a",
            "ms-a",
            EXPLORER_ORIGIN,
            now=150,
        )
        is not None
    )
    second_id = record_explorer_approval(config_store, auth_store, "loxberry:read", second, now=150)

    assert first_id == second_id
    assert len(config_store.load().explorer_bindings) == 1


def test_explorer_binding_isolated_by_capability_identity_and_miniserver(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    record_explorer_approval(config_store, auth_store, "loxberry:read", family(), now=100)
    config = config_store.load()

    assert (
        active_explorer_binding(
            config, auth_store, "loxberry:operate", "identity-a", "ms-a", EXPLORER_ORIGIN, now=150
        )
        is None
    )
    assert (
        active_explorer_binding(
            config, auth_store, "loxberry:read", "identity-b", "ms-a", EXPLORER_ORIGIN, now=150
        )
        is None
    )
    assert (
        active_explorer_binding(
            config, auth_store, "loxberry:read", "identity-a", "ms-b", EXPLORER_ORIGIN, now=150
        )
        is None
    )


def test_inactive_retention_is_independent_of_oauth_credentials(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    binding = record_explorer_approval(config_store, auth_store, "loxberry:read", family(), now=100)
    approval = config_store.load().explorer_bindings[0]
    config_store.save(
        replace(
            config_store.load(),
            explorer_binding_retention_hours=1,
            explorer_bindings=(replace(approval, inactive_since=200),),
        )
    )

    assert (
        active_explorer_binding(
            config_store.load(),
            auth_store,
            "loxberry:read",
            "identity-a",
            "ms-a",
            EXPLORER_ORIGIN,
            now=3799,
        )
        is not None
    )
    assert maintain_explorer_bindings(config_store, auth_store, now=3800) == 1
    assert config_store.load().explorer_bindings == ()
    assert binding == explorer_binding_id(
        auth_store, "loxberry:read", "identity-a", "ms-a", EXPLORER_ORIGIN
    )


def test_overdue_binding_fails_closed_before_scheduled_cleanup(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    config_store.save(replace(config_store.load(), explorer_binding_retention_hours=1))
    record_explorer_approval(config_store, auth_store, "loxberry:read", family(), now=100)

    assert (
        active_explorer_binding(
            config_store.load(),
            auth_store,
            "loxberry:read",
            "identity-a",
            "ms-a",
            EXPLORER_ORIGIN,
            now=3800,
        )
        is None
    )


def test_explorer_binding_isolated_by_validated_origin(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    record_explorer_approval(config_store, auth_store, "loxberry:read", family(), now=100)
    config = config_store.load()

    assert (
        active_explorer_binding(
            config, auth_store, "loxberry:read", "identity-a", "ms-a", EXPLORER_ORIGIN, now=150
        )
        is not None
    )
    assert (
        active_explorer_binding(
            config,
            auth_store,
            "loxberry:read",
            "identity-a",
            "ms-a",
            "https://alias.example",
            now=150,
        )
        is None
    )


def test_active_family_prevents_cleanup_until_last_family_ends(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    config_store.save(replace(config_store.load(), explorer_binding_retention_hours=1))
    record = family()
    record["expires_at"] = 20_000
    record_explorer_approval(config_store, auth_store, "loxberry:read", record, now=100)

    def insert(document: dict[str, object]) -> None:
        document["families"]["family-a"] = record  # type: ignore[index]

    auth_store.mutate(insert)
    assert maintain_explorer_bindings(config_store, auth_store, now=10_000) == 0
    assert config_store.load().explorer_bindings[0].inactive_since is None


def test_pending_family_does_not_extend_an_expired_approval(tmp_path: Path) -> None:
    config_store, auth_store = stores(tmp_path)
    config_store.save(replace(config_store.load(), explorer_binding_retention_hours=1))
    record_explorer_approval(config_store, auth_store, "loxberry:read", family(), now=100)
    pending = family(client_id="pending-client")
    pending["expires_at"] = 20_000

    def insert(document: dict[str, object]) -> None:
        document["families"]["pending"] = pending  # type: ignore[index]

    auth_store.mutate(insert)

    assert maintain_explorer_bindings(config_store, auth_store, now=3_800) == 1
    assert config_store.load().explorer_bindings == ()
