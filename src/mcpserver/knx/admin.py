"""Narrow administrative metadata actions; no Miniserver operations."""

from __future__ import annotations

import base64
import binascii
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

from .catalog_service import CatalogService
from .drafts import DraftStore
from .import_repository import ImportRepository
from .model import MAX_FILE_BYTES, KnxError
from .store import KnxStore


def validate_active_labels(config: PluginConfig) -> None:
    """Keep legacy configuration writes within the shared active-label bound."""
    data_root = os.getenv("LBPDATA", "")
    if not data_root or not config.loxone_endpoint:
        return
    path = Path(data_root) / "knx" / "metadata.sqlite3"
    if not path.exists():
        return
    target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    manual = config.knx_address_taxonomy if config.knx_address_taxonomy_endpoint == target else ()
    active: set[tuple[str, str]] = {(entry.address_format, entry.prefix) for entry in manual}
    try:
        active.update(
            (entry["address_format"], entry["prefix"])
            for entry in ImportRepository(KnxStore(path)).selected_labels(target)
        )
    except KnxError as exc:
        from mcpserver.admin import AdminError

        raise AdminError("KNX storage unavailable", code=exc.code) from None
    if len(active) > 128:
        from mcpserver.admin import AdminError

        raise AdminError("KNX active label limit exceeded", code="knx_label_limit")


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
        "knx_import_load",
        "knx_import_preview",
        "knx_import_apply",
        "knx_import_discard",
    }
    if action not in allowed or not isinstance(payload, dict):
        raise AdminError("Unsupported KNX action")
    try:
        return config_store.transaction(lambda config, save: _run(action, payload, config, save))
    except KnxError as exc:
        raise AdminError("KNX operation rejected", code=exc.code) from None


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
    import_fields = {
        "knx_import_load": {
            "target",
            "file",
            "encoding",
            "complete_export",
            "address_format",
            "file_format",
        },
        "knx_import_preview": {
            "target",
            "draft_id",
            "choices",
            "selected_groups",
            "mode",
            "orphan_name_policy",
            "offset",
            "conflict_offset",
        },
        "knx_import_apply": {"target", "draft_id", "preview_token"},
        "knx_import_discard": {"target", "draft_id"},
    }
    if action in import_fields and not payload.keys() <= import_fields[action]:
        raise KnxError("knx_preview_invalid")
    data_root = os.getenv("LBPDATA", "")
    if not data_root or not Path(data_root).is_absolute():
        raise AdminError("Plugin data directory unavailable")
    store = KnxStore(Path(data_root) / "knx" / "metadata.sqlite3")
    repository = ImportRepository(store)
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
        active: set[tuple[str, str]] = {(entry.address_format, entry.prefix) for entry in entries}
        active.update(
            (entry["address_format"], entry["prefix"])
            for entry in repository.selected_labels(target)
        )
        if len(active) > 128:
            raise KnxError("knx_label_limit")
        save(replace(config, knx_address_taxonomy_endpoint=target, knx_address_taxonomy=entries))
        taxonomy_document = [
            {"prefix": e.prefix, "label": e.label, "address_format": e.address_format}
            for e in entries
        ]
        taxonomy_revision = hashlib.sha256(
            json.dumps(taxonomy_document, sort_keys=True).encode()
        ).hexdigest()
    if action.startswith("knx_import_"):
        drafts = DraftStore(
            Path(data_root) / "knx" / "drafts.sqlite3",
            os.getenv("MCPSERVER_KNX_ADMIN_SESSION", ""),
        )
        service = CatalogService(repository, drafts, target, taxonomy_document)
        if action == "knx_import_load":
            encoded = payload.get("file")
            if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
                raise KnxError("knx_file_limit")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise KnxError("knx_file_invalid") from None
            return {
                **service.create(
                    raw,
                    encoding=payload.get("encoding", "auto"),
                    complete_export=payload.get("complete_export", False),
                    address_format=payload.get("address_format"),
                    file_format=payload.get("file_format", "xml"),
                ),
                "target": token,
                "target_display": target,
            }
        identifier = payload.get("draft_id")
        if not isinstance(identifier, str):
            raise KnxError("knx_draft_invalid")
        if action == "knx_import_preview":
            return {
                **service.preview(
                    identifier,
                    {
                        key: value
                        for key, value in payload.items()
                        if key not in {"target", "draft_id"}
                    },
                ),
                "target": token,
                "target_display": target,
            }
        if action == "knx_import_discard":
            drafts.discard(identifier)
            return {"discarded": True}
        outcome = service.apply(identifier, payload.get("preview_token"))
        return {
            **store.page(target),
            "target": token,
            "target_display": target,
            "taxonomy": taxonomy_document,
            "taxonomy_revision": taxonomy_revision,
            "imported_labels": repository.selected_labels(target),
            **outcome,
        }
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
        "target_display": target,
        "taxonomy": taxonomy_document,
        "taxonomy_revision": taxonomy_revision,
        "imported_labels": repository.selected_labels(target),
    }
