"""Fixed loopback Admin bridge with separately authorized project evidence."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from mcpserver.admin_errors import AdminError

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from mcpserver.auth.provider import Phase0OAuthProvider, StoredAccessToken
    from mcpserver.auth.store import AtomicJsonAuthStore
    from mcpserver.config import AtomicConfigStore
    from mcpserver.loxone.runtime import LoxoneRuntime

PATH = "/internal/knx-admin-project"
MAX_REQUEST = 64 * 1024
MAX_RESPONSE = 21 * 1024 * 1024
PROOF_TTL = 60
ACTIONS = frozenset(
    {
        "knx_correction_apply",
        "knx_correction_xml_preview",
        "knx_correction_xml_download",
        "knx_project_page",
    }
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
    # A fixed plain loopback connection needs no proxy discovery, redirects or
    # TLS trust-store initialization. Host remains the validated public origin.
    connection = HTTPConnection("127.0.0.1", 8765, timeout=55)
    try:
        connection.request("POST", PATH, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise AdminError("Project operation unavailable", code="write_outcome_uncertain")
        result = json.loads(raw)
    except (HTTPException, OSError, ValueError):
        raise AdminError("Project operation unavailable", code="write_outcome_uncertain") from None
    finally:
        connection.close()
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
        self.comparison: Any = None

    def fresh(self, access: StoredAccessToken) -> None:
        """Fresh local OAuth validity at effects, without reading Admin config again."""
        from mcpserver.auth.scopes import READ_SCOPE
        from mcpserver.auth.store import token_digest

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
        from starlette.responses import JSONResponse

        from mcpserver.auth.scopes import READ_SCOPE
        from mcpserver.loxone.project.models import ProjectError
        from mcpserver.loxone.runtime import RuntimeUnavailable
        from mcpserver.persistence import PersistenceUncertain

        from .model import KnxError

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
        except (AdminError, KnxError) as exc:
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
        from mcpserver.loxone.endpoint import MiniserverEndpoint
        from mcpserver.loxone.project.models import ProjectError
        from mcpserver.loxone.runtime import RuntimeUnavailable
        from mcpserver.tools import _project_query

        from .admin import dispatch_knx
        from .correction_service import project_binding
        from .model import KnxError

        config = await asyncio.to_thread(self.configs.load)
        target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
        if (
            self.runtime.endpoint.origin != target
            or value["payload"].get("target") != hashlib.sha256(target.encode()).hexdigest()
        ):
            raise AdminError("Target changed", code="knx_target_conflict")
        if value["action"] == "knx_project_page":
            from mcpserver.tools import _ProjectAnalysisRunner

            from .project_metadata import ProjectMetadata
            from .read_model import table_order

            payload = value["payload"]
            if (
                type(payload.get("offset", 0)) is not int
                or not 0 <= payload.get("offset", 0) <= 65536
            ):
                raise KnxError("knx_page_invalid")
            if (
                not payload.keys() <= {"target", "revision", "offset", "sort"}
                or type(payload.get("revision")) is not int
            ):
                raise KnxError("knx_page_invalid")
            table_order(
                payload.get("sort"),
                (
                    "address",
                    "relation",
                    "loxone_names",
                    "imported_name",
                    "manual_name",
                    "observation",
                ),
            )
            if self.comparison is None:
                self.comparison = _ProjectAnalysisRunner(
                    self.runtime, self.configs, ProjectMetadata(self.metadata_path)
                )
            # The analysis runner admits each project/worker phase through the
            # runtime's shared semaphore. Do not acquire that same permit here.
            started = time.monotonic()
            envelope = await self.comparison.run(
                "knx",
                ["ets_project_comparison"],
                limit=50,
                admin_access=access,
                admin_table={"offset": payload.get("offset", 0), "sort": payload.get("sort")},
            )
            logging.getLogger(__name__).info(
                "component=project_load phase=admin_runner duration_ms=%.1f",
                (time.monotonic() - started) * 1000,
            )
            result: dict[str, Any] = envelope.model_dump(mode="json")
            data = result.get("data")
            summary = (
                data.get("summaries", {}).get("ets_project_comparison", {})
                if isinstance(data, dict)
                else {}
            )
            if result["ok"] and (
                summary.get("target_binding") != payload["target"]
                or summary.get("knx_revision") != payload["revision"]
            ):
                raise KnxError("knx_revision_conflict")
            if not verify(key, session, body, supplied, int(time.time())):
                raise PermissionError("Admin approval expired")
            await asyncio.to_thread(self.fresh, access)
            return result
        query, _ = await _project_query(self.runtime, access)

        loop = asyncio.get_running_loop()
        binding = project_binding(query)

        async def recheck(*, worker_admitted: bool) -> None:
            current, _ = await _project_query(self.runtime, access, worker_admitted=worker_admitted)
            if project_binding(current) != binding:
                raise KnxError("knx_project_evidence_changed")

        def authorize() -> None:
            try:
                if not verify(key, session, body, supplied, int(time.time())):
                    raise PermissionError("Admin approval expired")
                self.fresh(access)
                checking = asyncio.run_coroutine_threadsafe(recheck(worker_admitted=True), loop)
                try:
                    checking.result(timeout=15)
                except TimeoutError:
                    checking.cancel()
                    raise KnxError("knx_project_evidence_required") from None
                if not verify(key, session, body, supplied, int(time.time())):
                    raise PermissionError("Admin approval expired")
                self.fresh(access)
            except (PermissionError, ProjectError, RuntimeUnavailable):
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
                # One request spends one family read token. Retain its worker
                # lease through final evidence checks rather than readmitting it.
                if value["action"] == "knx_correction_apply":
                    await recheck(worker_admitted=True)
                # The export adapter already rechecks project evidence after
                # serialization, then checks proposal expiry before returning.
                await asyncio.to_thread(self.fresh, access)
            except (PermissionError, ProjectError, RuntimeUnavailable, KnxError):
                raise AdminError(
                    "Operation outcome uncertain", code="write_outcome_uncertain"
                ) from None
            return result
