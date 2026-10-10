"""Narrow administrative metadata actions; no Miniserver operations."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.project.taxonomy import parse_taxonomy

from .model import KnxError
from .store import KnxStore


def dispatch_knx(action: str, payload: object, config_store: AtomicConfigStore) -> dict[str, Any]:
    from mcpserver.admin import AdminError

    allowed = {
        "knx_page",
        "knx_put",
        "knx_delete",
        "knx_export",
        "knx_restore",
        "knx_taxonomy",
        "knx_preview",
    }
    if action not in allowed or not isinstance(payload, dict):
        raise AdminError("Unsupported KNX action")
    return config_store.transaction(lambda config, save: _run(action, payload, config, save))


def _run(
    action: str, payload: dict[str, Any], config: PluginConfig, save: Callable[[PluginConfig], None]
) -> dict[str, Any]:
    from mcpserver.admin import AdminError

    if not config.loxone_endpoint:
        raise AdminError("A configured Miniserver is required", code="knx_target_missing")
    target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    token = hashlib.sha256(target.encode()).hexdigest()
    if action not in {"knx_page", "knx_export"} and payload.get("target") != token:
        raise AdminError("KNX target changed; reload", code="knx_target_conflict")
    data_root = os.getenv("LBPDATA", "")
    if not data_root or not Path(data_root).is_absolute():
        raise AdminError("Plugin data directory unavailable")
    entries = config.knx_address_taxonomy if config.knx_address_taxonomy_endpoint == target else ()
    taxonomy_document = [
        {"prefix": e.prefix, "label": e.label, "address_format": e.address_format} for e in entries
    ]
    taxonomy_revision = hashlib.sha256(
        json.dumps(taxonomy_document, sort_keys=True).encode()
    ).hexdigest()
    if action == "knx_taxonomy":
        if payload.get("taxonomy_revision") != taxonomy_revision:
            raise AdminError("KNX labels changed; reload", code="knx_revision_conflict")
        try:
            entries = parse_taxonomy(payload.get("entries"))
        except ValueError:
            raise AdminError("KNX labels invalid", code="knx_field_invalid") from None
        save(replace(config, knx_address_taxonomy_endpoint=target, knx_address_taxonomy=entries))
        taxonomy_document = [
            {"prefix": e.prefix, "label": e.label, "address_format": e.address_format}
            for e in entries
        ]
        taxonomy_revision = hashlib.sha256(
            json.dumps(taxonomy_document, sort_keys=True).encode()
        ).hexdigest()
    store = KnxStore(Path(data_root) / "knx" / "metadata.sqlite3")
    try:
        if action == "knx_export":
            return {"document": store.export(target, payload.get("offset", 0)), "target": token}
        if action == "knx_preview":
            return {**store.preview(target, payload.get("document")), "target": token}
        if action == "knx_restore":
            store.restore(target, payload.get("revision"), payload.get("document"))
        elif action == "knx_put":
            store.put(target, payload.get("revision"), payload.get("record"))
        elif action == "knx_delete":
            store.delete(target, payload.get("revision"), payload.get("address_id"))
        page = store.page(target, payload.get("offset", 0))
    except KnxError as exc:
        raise AdminError("KNX operation rejected", code=exc.code) from None
    return {
        **page,
        "target": token,
        "taxonomy": taxonomy_document,
        "taxonomy_revision": taxonomy_revision,
    }
