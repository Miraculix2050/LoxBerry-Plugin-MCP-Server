"""Read-only end-to-end project diagnostic using one existing MCP OAuth family."""

import asyncio
import json
import logging
import time
from collections import Counter
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.provider import StoredAccessToken
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.client import LoxoneClient
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.service import ProjectService
from mcpserver.settings import ServerSettings


def select_family(document: dict, now: float) -> tuple[str, dict] | None:
    """Refuse ambiguous identities; never choose an administrator as fallback."""
    candidates = [
        (key, value)
        for key, value in document["families"].items()
        if not value.get("revoked", False)
        and value.get("expires_at", 0) > now
        and "loxone:read" in value.get("scope", "").split()
        and value.get("client_kind") != "tool_explorer"
    ]
    identities = {(v["identity_id"], v["miniserver_id"]) for _, v in candidates}
    if len(identities) != 1:
        return None
    return max(candidates, key=lambda item: item[1]["expires_at"])


async def run() -> dict[str, object]:
    settings = ServerSettings.from_environment().phase0_auth
    if settings is None or not settings.loxone_store_path or not settings.install_key_path:
        return {"result": "settings_unavailable"}
    if not all(
        path.is_file()
        for path in (settings.store_path, settings.loxone_store_path, settings.install_key_path)
    ):
        return {"result": "existing_session_required"}
    store = AtomicJsonAuthStore(settings.store_path)
    selected = select_family(store.snapshot(), time.time())
    if selected is None:
        return {"result": "unique_active_mcp_identity_required"}
    family_id, family = selected
    health = LoxoneTokenHealthStore(store)
    if health.get(family_id).confirmation_required:
        return {"result": "token_confirmation_required"}
    tokens = EncryptedLoxoneTokenStore(settings.loxone_store_path, settings.install_key_path)

    async def validate(access):
        current = store.snapshot()["families"].get(family_id, {})
        return bool(
            not current.get("revoked", True)
            and current.get("expires_at", 0) > time.time()
            and current.get("identity_id") == access.identity_id
            and current.get("miniserver_id") == access.miniserver_id
            and "loxone:read" in current.get("scope", "").split()
        )

    access = StoredAccessToken(
        token="local-diagnostic-context",
        client_id=family["client_id"],
        scopes=["loxone:read"],
        family_id=family_id,
        identity_id=family["identity_id"],
        miniserver_id=family["miniserver_id"],
    )
    client = LoxoneClient(
        settings.loxone_endpoint,
        client_uuid=uuid5(NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver"),
    )
    service = ProjectService(client, tokens, health, validate)
    token = None
    session = None
    started = time.monotonic()
    try:
        await service._check(access)
        token = tokens.get(family_id, access.miniserver_id, access.identity_id)
        if token is None:
            return {"result": "existing_token_required"}
        async with asyncio.timeout(20):
            session = await client.open_session(token)
            structure = await session.load_structure()
        await session.close()
        session = None
        view = await service.view(access, SimpleNamespace(subject=family_id, structure=structure))
        graph = view.snapshot.graph
        return {
            "result": "pipeline_verified",
            "transport": "encrypted_http_or_https",
            "projects": len(view.snapshot.projects),
            "nodes": len(graph.nodes),
            "edges": dict(Counter(edge.kind for edge in graph.edges)),
            "unresolved": len(graph.unresolved),
            "mapping": dict(Counter(entry.status for entry in view.mapping.entries)),
            "parser_anomalies": dict(
                Counter(
                    code for project in view.snapshot.projects for code in project.anomaly_codes
                )
            ),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    except ProjectError as exc:
        return {"result": str(exc)}
    except Exception:
        return {"result": "diagnostic_transport_or_processing_error"}
    finally:
        if session is not None:
            await session.close()
        if token is not None:
            token.destroy()
        await service.close()


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(run())
    except Exception:
        result = {"result": "diagnostic_setup_error"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "pipeline_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
