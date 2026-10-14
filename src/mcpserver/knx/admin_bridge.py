"""Fixed loopback Admin bridge with separately authorized project evidence."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcpserver.admin_errors import AdminError
from mcpserver.auth.provider import Phase0OAuthProvider, StoredAccessToken
from mcpserver.auth.scopes import READ_SCOPE
from mcpserver.auth.store import AtomicJsonAuthStore, token_digest
from mcpserver.config import AtomicConfigStore
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.runtime import LoxoneRuntime, RuntimeUnavailable
from mcpserver.persistence import PersistenceUncertain

from .model import KnxError

PATH = "/internal/knx-admin-project"
MAX_REQUEST = 64 * 1024
MAX_RESPONSE = 21 * 1024 * 1024
PROOF_TTL = 60
ACTIONS = frozenset(
    {"knx_correction_apply", "knx_correction_xml_preview", "knx_correction_xml_download"}
)
SESSION_HEADER = "X-LoxBerry-KNX-Admin-Session"
PROOF_HEADER = "X-LoxBerry-KNX-Admin-Proof"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def proof(key: str, session: str, body: bytes, issued: int) -> str:
    message = canonical([PATH, session, hashlib.sha256(body).hexdigest(), issued])
    return str(issued) + "." + hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def verify(key: str, session: str, body: bytes, supplied: str, now: int) -> bool:
    if not re.fullmatch(r"[0-9a-f]{64}", session) or not re.fullmatch(
        r"[0-9]{1,12}\.[0-9a-f]{64}", supplied
    ):
        return False
    issued = int(supplied.split(".")[0])
    return 0 <= now - issued <= PROOF_TTL and hmac.compare_digest(
        supplied, proof(key, session, body, issued)
    )


def helper_key(store: AtomicJsonAuthStore) -> str:
    return store.pseudonym("knx-admin-project-helper-v1")


def forward(action: str, payload: dict[str, Any], configs: AtomicConfigStore) -> dict[str, Any]:
    """Called only by the authenticated CGI helper, before any config lock."""
    from mcpserver.admin import _auth_store

    bearer = os.getenv("HTTP_X_LOXONE_AUTHORIZATION", "")
    session = os.getenv("MCPSERVER_KNX_ADMIN_SESSION", "")
    body = canonical({"action": action, "payload": payload})
    config = configs.load()
    if (
        action not in ACTIONS
        or len(body) > MAX_REQUEST
        or not bearer.startswith("Bearer ")
        or len(bearer) > 8192
    ):
        raise AdminError("Project evidence required", code="knx_project_evidence_required")
    issued = int(time.time())
    headers = {
        "Host": urlsplit(config.public_origin).netloc,
        "Authorization": bearer,
        "Content-Type": "application/json",
        SESSION_HEADER: session,
        PROOF_HEADER: proof(helper_key(_auth_store()), session, body, issued),
    }
    try:
        raw = bytearray()
        with httpx.stream(
            "POST",
            "http://127.0.0.1:8765" + PATH,
            headers=headers,
            content=body,
            timeout=55,
            trust_env=False,
        ) as response:
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE:
                    raise AdminError(
                        "Project operation unavailable", code="write_outcome_uncertain"
                    )
        result = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        raise AdminError("Project operation unavailable", code="write_outcome_uncertain") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        error = result.get("error") if isinstance(result, dict) else None
        code = error.get("code") if isinstance(error, dict) else error
        raise AdminError(
            "Project operation rejected",
            code=code
            if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,80}", code)
            else "write_outcome_uncertain",
        )
    if not isinstance(result.get("data"), dict):
        raise AdminError("Project operation unavailable", code="write_outcome_uncertain")
    return cast(dict[str, Any], result["data"])


class AdminProjectBridge:
    def __init__(
        self,
        store: AtomicJsonAuthStore,
        configs: AtomicConfigStore,
        provider: Phase0OAuthProvider,
        runtime: LoxoneRuntime,
        metadata_path: Path,
        admission: asyncio.Semaphore,
    ) -> None:
        self.store, self.configs, self.provider, self.runtime = store, configs, provider, runtime
        self.metadata_path, self.admission = metadata_path, admission
        self.slots = asyncio.Semaphore(configs.load().max_parallel_calls)
        self.workers: set[asyncio.Task[dict[str, Any]]] = set()

    def fresh(self, access: StoredAccessToken) -> None:
        """Fresh local OAuth validity at effects, without reading Admin config again."""
        state = self.store.snapshot()
        record = state["access_tokens"].get(token_digest(access.token), {})
        family = state["families"].get(access.family_id, {})
        now = self.provider.now()
        if (
            record.get("status") != "active"
            or record.get("expires_at", 0) <= now
            or not family
            or family.get("revoked")
            or family.get("expires_at", 0) <= now
            or record.get("family_id") != access.family_id
            or READ_SCOPE not in record.get("scopes", [])
            or record.get("client_id") != access.client_id
            or record.get("identity_id") != access.identity_id
            or record.get("miniserver_id") != access.miniserver_id
            or record.get("resource") != access.resource
        ):
            raise PermissionError("Project access revoked")

    async def handle(self, request: Request) -> JSONResponse:
        session = request.headers.get(SESSION_HEADER, "")
        supplied = request.headers.get(PROOF_HEADER, "")
        raw = bytearray()
        if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse(
                {"ok": False, "error": {"code": "permission_denied"}}, status_code=403
            )
        key = await asyncio.to_thread(helper_key, self.store)
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_REQUEST:
                return JSONResponse(
                    {"ok": False, "error": {"code": "knx_file_limit"}}, status_code=413
                )
        if not verify(key, session, bytes(raw), supplied, int(time.time())):
            return JSONResponse(
                {"ok": False, "error": {"code": "permission_denied"}}, status_code=403
            )
        try:
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or set(value) != {"action", "payload"}
                or value.get("action") not in ACTIONS
                or not isinstance(value.get("payload"), dict)
            ):
                raise AdminError("Invalid operation", code="knx_correction_invalid")
            bearer = request.headers.get("Authorization", "")
            access = (
                await asyncio.to_thread(
                    lambda: asyncio.run(self.provider.load_access_token(bearer[7:]))
                )
                if bearer.startswith("Bearer ") and len(bearer) <= 8192
                else None
            )
            if access is None or READ_SCOPE not in access.scopes:
                raise PermissionError("Project access required")
            result = await asyncio.wait_for(
                self.execute(value, session, key, supplied, bytes(raw), access), timeout=50
            )
            return JSONResponse({"ok": True, "data": result})
        except (PermissionError, ProjectError, RuntimeUnavailable):
            code = "knx_project_evidence_required"
        except AdminError as exc:
            code = exc.code
        except (PersistenceUncertain, TimeoutError):
            code = "write_outcome_uncertain"
        except (ValueError, TypeError, KeyError):
            code = "knx_correction_invalid"
        return JSONResponse({"ok": False, "error": {"code": code}})

    async def execute(
        self,
        value: dict[str, Any],
        session: str,
        key: str,
        supplied: str,
        body: bytes,
        access: StoredAccessToken,
    ) -> dict[str, Any]:
        # Cancellation while waiting for a slot starts no background work. Once
        # admitted, the task owns both leases through the actual worker completion.
        await self.slots.acquire()
        worker = asyncio.create_task(self._execute(value, session, key, supplied, body, access))
        self.workers.add(worker)

        def finished(task: asyncio.Task[dict[str, Any]]) -> None:
            self.workers.discard(task)
            self.slots.release()
            if not task.cancelled():
                task.exception()

        worker.add_done_callback(finished)
        return await asyncio.shield(worker)

    async def _execute(
        self,
        value: dict[str, Any],
        session: str,
        key: str,
        supplied: str,
        body: bytes,
        access: StoredAccessToken,
    ) -> dict[str, Any]:
        from mcpserver.tools import _project_query

        from .admin import dispatch_knx

        config = await asyncio.to_thread(self.configs.load)
        target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
        if (
            self.runtime.endpoint.origin != target
            or value["payload"].get("target") != hashlib.sha256(target.encode()).hexdigest()
        ):
            raise AdminError("Target changed", code="knx_target_conflict")
        query, _ = await _project_query(self.runtime, access)

        def authorize() -> None:
            try:
                if not verify(key, session, body, supplied, int(time.time())):
                    raise PermissionError("Admin approval expired")
                self.fresh(access)
            except PermissionError:
                # PermissionError is an OSError; config transactions would
                # otherwise sanitize revocation as a persistence failure.
                raise KnxError("knx_project_evidence_required") from None

        async with self.admission:
            result = await asyncio.to_thread(
                dispatch_knx,
                value["action"],
                value["payload"],
                self.configs,
                query=query,
                authorize_effect=authorize,
                admin_session=session,
                metadata_path=self.metadata_path,
            )
        try:
            await asyncio.to_thread(authorize)
            assert self.runtime.projects is not None
            await self.runtime.projects.authorize(access)
        except (PermissionError, ProjectError, KnxError):
            raise AdminError(
                "Operation outcome uncertain", code="write_outcome_uncertain"
            ) from None
        return result
