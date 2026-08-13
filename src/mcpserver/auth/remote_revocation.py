"""Durable best-effort cleanup of Loxone tokens after local OAuth revocation."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Final
from uuid import UUID

from mcpserver.auth.loxone_store import (
    EncryptedLoxoneTokenStore,
    LoxoneTokenStoreError,
    RemoteRevocation,
)
from mcpserver.loxone.client import LoxoneClient, LoxoneConnectionError, MiniserverEndpoint
from mcpserver.loxone.events import LoxoneProtocolError

_LOGGER = logging.getLogger("mcpserver.auth.remote_revocation")
_POLL_SECONDS: Final = 5
_CLIENT_UUID: Final = UUID("3f52f6fe-3af0-4d30-a8bb-f429b9da4465")


async def process_remote_revocations(
    endpoint: MiniserverEndpoint,
    store: EncryptedLoxoneTokenStore,
    timeout_seconds: float,
) -> None:
    """Delete only tokens whose remote killtoken operation succeeded."""
    try:
        pending = store.pending_remote_revocations(int(time.time()))
    except LoxoneTokenStoreError as exc:
        _LOGGER.warning(
            "component=remote_revocation outcome=queue_unavailable error_type=%s",
            type(exc).__name__,
        )
        return
    if not pending:
        return
    client = LoxoneClient(endpoint, client_uuid=_CLIENT_UUID, timeout_seconds=timeout_seconds)

    async def process(item: RemoteRevocation) -> None:
        # Keep identifiers and tokens out of logs.
        try:
            await asyncio.wait_for(client.kill_token(item.token), timeout=timeout_seconds + 5)
        except (TimeoutError, LoxoneConnectionError, LoxoneProtocolError):
            with suppress(LoxoneTokenStoreError):
                store.defer_remote_revoke(item.family_id, int(time.time()))
            _LOGGER.warning("component=remote_revocation outcome=deferred")
        else:
            with suppress(LoxoneTokenStoreError):
                store.complete_remote_revoke(item.family_id)
            _LOGGER.info("component=remote_revocation outcome=completed")

    async with asyncio.TaskGroup() as group:
        for item in pending:
            group.create_task(process(item))


async def run_remote_revocation_worker(
    endpoint: MiniserverEndpoint,
    store: EncryptedLoxoneTokenStore,
    timeout_seconds: float,
) -> None:
    """Continue deferred cleanup across CGI requests and service restarts."""
    while True:
        await process_remote_revocations(endpoint, store, timeout_seconds)
        await asyncio.sleep(_POLL_SECONDS)
