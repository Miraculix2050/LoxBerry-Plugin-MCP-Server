"""Authorized, bounded local KNX reads with revision-bound continuation."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from mcpserver.auth.provider import StoredAccessToken
from mcpserver.config import AtomicConfigStore

from .catalog import catalog_page, catalog_prefix_page, labels_revision
from .delegation import authorize_read
from .model import KnxError, address_number
from .read_model import query_filters
from .store import KnxStore


class CatalogUnavailable(RuntimeError):
    """A bounded admission or rate limit rejected the request."""


class CatalogCursors:
    """Short-lived signed offsets; no catalog is retained per client or cursor."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def encode(self, scope: str, offset: int, revision: int, expires: int) -> str:
        body = json.dumps(
            {"scope": scope, "offset": offset, "revision": revision, "expires": expires},
            separators=(",", ":"),
        ).encode()
        signature = hmac.new(self._key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")

    def decode(self, scope: str, value: str, now: int) -> tuple[int, int, int]:
        if not isinstance(value, str) or not 1 <= len(value) <= 512:
            raise ValueError("KNX cursor is invalid")
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            body, signature = raw[:-32], raw[-32:]
            if not hmac.compare_digest(
                signature, hmac.new(self._key, body, hashlib.sha256).digest()
            ):
                raise ValueError
            document = json.loads(body)
            if not isinstance(document, dict) or set(document) != {
                "scope",
                "offset",
                "revision",
                "expires",
            }:
                raise ValueError
            offset, revision, expires = (document[key] for key in ("offset", "revision", "expires"))
            if (
                document["scope"] != scope
                or any(type(item) is not int for item in (offset, revision, expires))
                or not 0 <= offset <= 65536
                or not 0 <= revision < 2**63
                or expires <= now
                or expires > now + 300
            ):
                raise ValueError
            return offset, revision, expires
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("KNX cursor is invalid") from None


class CatalogRuntime:
    """One read service sharing server admission, without Loxone downloads or a second graph."""

    def __init__(
        self,
        path: Path,
        config_store: AtomicConfigStore,
        auth_store: Any,
        admission: asyncio.Semaphore,
    ) -> None:
        self.store = KnxStore(path)
        self.config_store = config_store
        self.auth_store = auth_store
        self.admission = admission
        self.cursors = CatalogCursors()
        self._rate: dict[str, deque[float]] = {}
        self._rate_lock = threading.Lock()

    def _consume_rate(self, family: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            if len(self._rate) >= 256:
                self._rate = {
                    key: values
                    for key, values in self._rate.items()
                    if values and values[-1] > now - 60
                }
            if family not in self._rate and len(self._rate) >= 256:
                raise CatalogUnavailable("Local KNX read capacity reached")
            entries = self._rate.setdefault(family, deque())
            while entries and entries[0] <= now - 60:
                entries.popleft()
            if len(entries) >= 30:
                raise CatalogUnavailable("Local KNX read rate limit reached")
            entries.append(now)

    def read(
        self,
        access: StoredAccessToken,
        *,
        query: str = "",
        source: str = "all",
        deviations_only: bool = False,
        address: str | None = None,
        view: str = "entries",
        kind: str = "addresses",
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if view not in {"entries", "summary"} or (view == "summary" and cursor is not None):
            raise ValueError("Invalid local KNX view")
        if kind not in {"addresses", "prefix_labels"} or (
            kind == "prefix_labels" and address is not None
        ):
            raise ValueError("Invalid local KNX record kind")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid local KNX page limit")
        number = address_number(address) if address is not None else None
        if address is not None and (number is None or address.endswith((":0", ":1"))):
            raise ValueError("Use an exact two-/three-level address without variant suffix")
        filters = query_filters(
            {"query": query, "source": source, "deviations_only": deviations_only}
        )
        config = self.config_store.load()
        target = authorize_read(config, self.auth_store, access)
        self._consume_rate(access.family_id)
        manual_revision = labels_revision(config, target)
        target_id = hashlib.sha256(target.encode()).hexdigest()
        scope = hashlib.sha256(
            json.dumps(
                [
                    access.family_id,
                    access.client_id,
                    access.identity_id,
                    access.miniserver_id,
                    target_id,
                    manual_revision,
                    filters,
                    number,
                    view,
                    kind,
                    limit,
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        now = int(time.time())
        offset, expected, _previous_expiry = (
            (0, None, now + 300) if cursor is None else self.cursors.decode(scope, cursor, now)
        )
        expires = now + 300
        data = (
            catalog_page(
                self.store,
                config,
                target,
                offset=offset,
                limit=limit,
                filters=filters,
                expected=expected,
                address_id=number,
                count_only=view == "summary",
            )
            if kind == "addresses"
            else catalog_prefix_page(
                self.store,
                config,
                target,
                offset=offset,
                limit=limit,
                filters=filters,
                expected=expected,
                count_only=view == "summary",
            )
        )
        data.setdefault("prefix_labels", [])
        item_key = "records" if kind == "addresses" else "prefix_labels"
        records = data[item_key]
        context = data["prefix_context"]

        def project(count: int) -> dict[str, Any]:
            retained = records[:count]
            used = {identifier for row in retained for identifier in row.get("prefix_ids", [])}
            next_offset = offset + count
            return {
                **data,
                "view": view,
                "target_id": target_id,
                item_key: retained,
                "kind": kind,
                "returned": count,
                "prefix_context": [row for row in context if row["prefix_id"] in used],
                "page_truncated": count < len(records),
                "next_cursor": self.cursors.encode(scope, next_offset, data["revision"], expires)
                if view == "entries" and next_offset < data["total_matching"]
                else None,
            }

        # Reserve envelope overhead and keep entire rows. Binary search avoids
        # serializing the full large page once for every removed record.
        projected = project(len(records))
        maximum_bytes = 65536 - 1024
        if (
            len(json.dumps(projected, separators=(",", ":"), ensure_ascii=False).encode())
            > maximum_bytes
        ):
            lower, upper = 0, len(records)
            while lower < upper:
                count = (lower + upper + 1) // 2
                candidate = project(count)
                if (
                    len(json.dumps(candidate, separators=(",", ":"), ensure_ascii=False).encode())
                    <= maximum_bytes
                ):
                    lower = count
                else:
                    upper = count - 1
            if not lower:
                raise CatalogUnavailable("Local KNX record exceeds response limit")
            projected = project(lower)
        current = self.config_store.load()
        if (
            authorize_read(current, self.auth_store, access) != target
            or labels_revision(current, target) != manual_revision
        ):
            raise KnxError("knx_revision_conflict")
        return projected

    async def run(self, access: StoredAccessToken, **arguments: Any) -> dict[str, Any]:
        await asyncio.wait_for(self.admission.acquire(), timeout=10)
        worker: asyncio.Task[dict[str, Any]] | None = None
        try:
            worker = asyncio.create_task(asyncio.to_thread(self.read, access, **arguments))
            return await asyncio.wait_for(asyncio.shield(worker), timeout=10)
        finally:
            if worker is None or worker.done():
                self.admission.release()
            else:
                # A timed-out/cancelled client cannot release the slot while
                # its actual SQLite work is still running in the thread.
                def finished(task: asyncio.Task[dict[str, Any]]) -> None:
                    if not task.cancelled():
                        task.exception()
                    self.admission.release()

                worker.add_done_callback(finished)
