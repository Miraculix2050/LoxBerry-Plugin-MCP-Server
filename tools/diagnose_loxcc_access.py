"""Bounded, secret-safe project-download probe using an existing MCP identity.

Run locally on the authorized LoxBerry with the service environment. This is a
developer diagnostic, not an MCP tool. Never persist the received project.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import struct
import time
import zipfile
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from mcpserver.auth.loxone_health import LoxoneTokenHealthStore
from mcpserver.auth.loxone_store import EncryptedLoxoneTokenStore
from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.loxone.client import LoxoneClient
from mcpserver.loxone.security import CommandEncryptor
from mcpserver.settings import ServerSettings

MAX_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
TIMEOUT = 20
COMMAND = "dev/fsget/prog/sps.LoxCC"


def classify_zip(payload: bytes) -> dict[str, object]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) > 32 or sum(e.file_size for e in entries) > MAX_DECODED_BYTES:
                return {"result": "size_limit"}
            projects = [
                e for e in entries if not e.is_dir() and e.filename.lower().endswith(".loxcc")
            ]
            if not projects:
                return {"result": "zip_without_project"}
            for entry in projects:
                if entry.file_size > MAX_BYTES or entry.flag_bits & 1:
                    return {"result": "unsupported_zip_entry"}
                with archive.open(entry) as source:
                    member = source.read(MAX_BYTES + 1)
                if member.startswith(b"PK") or classify(member)["result"] != "download_verified":
                    return {"result": "invalid_zip_project"}
            return {
                "result": "download_verified",
                "format": "zip",
                "bytes": len(payload),
                "project_count": len(projects),
                "validation": "zip_crc_and_loxcc_headers_only",
            }
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        return {"result": "invalid_zip"}


def classify(payload: str | bytes | None) -> dict[str, object]:
    """Validate the LoxCC envelope only; decoding/CRC is a separate issue."""
    if payload is None:
        return {"result": "empty_response"}
    if len(payload) > MAX_BYTES:
        return {"result": "size_limit"}
    if isinstance(payload, str):
        try:
            reply = json.loads(payload)
            code = str(reply.get("LL", {}).get("Code", ""))
        except (ValueError, AttributeError):
            code = ""
        return {
            "result": "request_rejected" if code in {"401", "403"} else "non_project_response",
            **({"status_code": int(code)} if code in {"401", "403", "404"} else {}),
        }
    if payload.startswith(b"PK\x03\x04"):
        return classify_zip(payload)
    if len(payload) < 16:
        return {"result": "invalid_header"}
    magic, compressed, decoded, _crc = struct.unpack_from("<IIII", payload)
    if magic != 0xAABBCCEE:
        return {"result": "non_project_response"}
    if not 0 < decoded <= MAX_DECODED_BYTES or not 0 < compressed <= MAX_BYTES - 16:
        return {"result": "size_limit"}
    if compressed != len(payload) - 16:
        return {"result": "invalid_length"}
    return {
        "result": "download_verified",
        "format": "loxcc",
        "bytes": len(payload),
        "decoded_bytes_declared": decoded,
        "validation": "header_and_length_only",
    }


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


async def fetch_http(client, session, token) -> dict[str, object]:
    command = f"{COMMAND}?autht={quote(token.value, safe='')}&user={quote(token.username, safe='')}"
    path = (
        f"/{command}"
        if client.endpoint.secure
        else CommandEncryptor.generate().encrypted_http_request(command, session._public_key)
    )
    async with (
        httpx.AsyncClient(
            base_url=client.endpoint.origin,
            follow_redirects=False,
            timeout=TIMEOUT,
            trust_env=False,
        ) as http,
        http.stream("GET", path, headers={"Accept-Encoding": "identity"}) as response,
    ):
        if response.status_code != 200:
            return {"result": "http_rejected", "status_code": response.status_code}
        body = bytearray()
        async for chunk in response.aiter_raw(chunk_size=65536):
            if len(body) + len(chunk) > MAX_BYTES:
                return {"result": "size_limit"}
            body.extend(chunk)
        return classify(bytes(body))


async def run(transport: str = "websocket") -> dict[str, object]:
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
    if LoxoneTokenHealthStore(store).get(family_id).confirmation_required:
        return {"result": "token_confirmation_required"}
    tokens = EncryptedLoxoneTokenStore(settings.loxone_store_path, settings.install_key_path)
    token = tokens.get(family_id, family["miniserver_id"], family["identity_id"])
    if token is None:
        return {"result": "existing_token_required"}
    session = None
    stage = "authentication"
    try:
        client = LoxoneClient(
            settings.loxone_endpoint,
            client_uuid=uuid5(NAMESPACE_URL, "https://loxberry.local/plugins/mcpserver"),
            timeout_seconds=TIMEOUT,
            max_response_bytes=MAX_BYTES,
        )
        async with asyncio.timeout(TIMEOUT):
            session = await client.open_session(token)
            stage = "download"
            if transport == "http":
                result = await fetch_http(client, session, token)
            else:
                # Isolated diagnostic session: no event reader competes for frames.
                command = (
                    COMMAND
                    if settings.loxone_endpoint.secure
                    else session._encryptor.encrypted_command(COMMAND)
                )
                await session._websocket.send(command)
                _header, payload = await session._receive()
                result = classify(payload)
            current = store.snapshot()["families"].get(family_id, {})
            if current.get("revoked", True) or current.get("expires_at", 0) <= time.time():
                return {"result": "session_revoked"}
            return {"stage": stage, "transport": transport, **result}
    except TimeoutError:
        return {"result": "timeout", "stage": stage}
    except Exception:
        # Exception messages can include URLs, credentials or response content.
        return {"result": "transport_or_authentication_error", "stage": stage}
    finally:
        if session is not None:
            await session.close()
        token.destroy()  # In-memory copy only; do not revoke or rotate the live token.


def main() -> int:
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("websocket", "http"), default="websocket")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.transport))
    except Exception:
        result = {"result": "diagnostic_setup_error"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "download_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
