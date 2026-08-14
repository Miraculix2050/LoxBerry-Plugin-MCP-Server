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
from mcpserver.loxone.client import (
    LoxoneClient,
    LoxoneCommandRejected,
    LoxoneConnectionError,
    LoxoneSourceIpBlocked,
    MiniserverEndpoint,
)
from mcpserver.loxone.events import LoxoneProtocolError

_LOGGER = logging.getLogger("mcpserver.auth.remote_revocation")
_POLL_SECONDS: Final = 5
_AUTHENTICATION_RETRY_SECONDS: Final = 3_600
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

    async def process(item: RemoteRevocation) -> bool:
        # Keep identifiers and tokens out of logs.
        try:
            await asyncio.wait_for(client.kill_token(item.token), timeout=timeout_seconds + 5)
        except LoxoneSourceIpBlocked:
            store.suspend_remote_revoke(
                item.family_id, int(time.time()), delay_seconds=_AUTHENTICATION_RETRY_SECONDS
            )
            _LOGGER.warning("component=remote_revocation outcome=source_ip_blocked")
            return False
        except LoxoneCommandRejected:
            store.suspend_remote_revoke(
                item.family_id, int(time.time()), delay_seconds=_AUTHENTICATION_RETRY_SECONDS
            )
            _LOGGER.warning("component=remote_revocation outcome=authentication_rejected")
            return False
        except (TimeoutError, LoxoneConnectionError, LoxoneProtocolError):
            with suppress(LoxoneTokenStoreError):
                store.defer_remote_revoke(item.family_id, int(time.time()))
            _LOGGER.warning("component=remote_revocation outcome=deferred")
            return True
        else:
            with suppress(LoxoneTokenStoreError):
                store.complete_remote_revoke(item.family_id)
            _LOGGER.info("component=remote_revocation outcome=completed")
            return True

    for index, item in enumerate(pending):
        if await process(item):
            continue
        for remaining in pending[index + 1 :]:
            with suppress(LoxoneTokenStoreError):
                store.suspend_remote_revoke(
                    remaining.family_id,
                    int(time.time()),
                    delay_seconds=_AUTHENTICATION_RETRY_SECONDS,
                )
        return


async def run_remote_revocation_worker(
    endpoint: MiniserverEndpoint,
    store: EncryptedLoxoneTokenStore,
    timeout_seconds: float,
) -> None:
    """Continue deferred cleanup across CGI requests and service restarts."""
    while True:
        await process_remote_revocations(endpoint, store, timeout_seconds)
        await asyncio.sleep(_POLL_SECONDS)
