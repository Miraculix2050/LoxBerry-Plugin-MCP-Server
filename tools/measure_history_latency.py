"""Read-only target phase probe for one visible native History control."""

import asyncio
import json
import logging
import time
from uuid import NAMESPACE_URL, uuid5

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.client import LoxoneClient
from mcpserver.settings import ServerSettings


async def run() -> dict[str, object]:
    settings = ServerSettings.from_environment().phase0_auth
    if settings is None or not settings.loxone_store_path or not settings.install_key_path:
        return {"result": "settings_unavailable"}
    store = AtomicJsonAuthStore(settings.store_path)
    now = time.time()
    candidates = [
        (family_id, family)
        for family_id, family in store.snapshot()["families"].items()
        if family.get("client_kind") == "tool_explorer"
        and not family.get("revoked", False)
        and family.get("expires_at", 0) > now
        and "loxone:history" in family.get("scope", "").split()
    ]
    if len({(f["identity_id"], f["miniserver_id"]) for _, f in candidates}) != 1:
        return {"result": "unique_active_history_identity_required"}
    family_id, family = max(candidates, key=lambda item: item[1]["expires_at"])
    if LoxoneTokenHealthStore(store).get(family_id).confirmation_required:
        return {"result": "token_confirmation_required"}
    tokens = EncryptedLoxoneTokenStore(settings.loxone_store_path, settings.install_key_path)
    token = tokens.get(family_id, family["miniserver_id"], family["identity_id"])
    if token is None:
        return {"result": "existing_token_required"}
    client = LoxoneClient(
        settings.loxone_endpoint,
        client_uuid=uuid5(NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver"),
    )
    runs: list[dict[str, float | int]] = []
    try:
        for _ in range(3):
            session = None
            try:
                phase = time.monotonic()
                async with asyncio.timeout(30):
                    session = await client.open_session(token)
                connection = time.monotonic() - phase
                phase = time.monotonic()
                async with asyncio.timeout(30):
                    structure = await session.load_structure()
                structure_seconds = time.monotonic() - phase
                phase = time.monotonic()
                control = next(
                    (item for item in structure.controls if item.has_history and item.action_uuid),
                    None,
                )
                visibility = time.monotonic() - phase
                if control is None:
                    return {"result": "no_visible_history_control"}
                phase = time.monotonic()
                async with asyncio.timeout(30):
                    raw = await session.control_history(control.action_uuid)
                fetch = time.monotonic() - phase
                phase = time.monotonic()
                count = len(raw[:1000])
                parse = time.monotonic() - phase
                runs.append(
                    {
                        "connection_s": round(connection, 3),
                        "structure_s": round(structure_seconds, 3),
                        "visibility_s": round(visibility, 3),
                        "fetch_s": round(fetch, 3),
                        "parse_s": round(parse, 3),
                        "entries": count,
                    }
                )
            finally:
                if session is not None:
                    await session.close()
    except Exception as exc:
        return {"result": "history_probe_failed", "error_type": type(exc).__name__, "runs": runs}
    finally:
        token.destroy()
    return {"result": "history_phases_measured", "runs": runs}


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(run())
    except Exception as exc:
        result = {"result": "history_probe_setup_failed", "error_type": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "history_phases_measured" else 2


if __name__ == "__main__":
    raise SystemExit(main())
