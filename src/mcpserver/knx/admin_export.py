"""Accepted correction handoff into the existing session-bound XML preview."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from mcpserver.config import PluginConfig
from mcpserver.loxone.project.query import ProjectQuery

from .correction_drafts import CorrectionDraftStore
from .correction_service import CorrectionService
from .drafts import DraftStore
from .model import KnxError
from .store import KnxStore
from .xml_export import XmlCorrectionExport


def correction_export(
    action: str,
    payload: dict[str, Any],
    config: PluginConfig,
    store: KnxStore,
    target: str,
    token: str,
    session: str,
    *,
    query: ProjectQuery | None,
    authorize: Callable[[], object],
) -> dict[str, Any]:
    drafts = DraftStore(store.path.with_name("drafts.sqlite3"), session)
    shared = CorrectionDraftStore(drafts.path, session)
    exporter = XmlCorrectionExport(store, drafts, target)
    if action == "knx_correction_xml_preview":
        fields = {
            "target",
            "draft_id",
            "draft_revision",
            "catalog_revision",
            "manual_revision",
            "approved_change_ids",
        }
        if set(payload) != fields:
            raise KnxError("knx_correction_invalid")
        binding = {key: payload[key] for key in fields - {"target"}}
    else:
        if set(payload) != {"target", "draft_id", "revision", "confirmed_experimental"}:
            raise KnxError("knx_correction_invalid")
        _, options = drafts.load(payload["draft_id"], target, payload["revision"])
        handoff = options.get("correction_handoff")
        if not isinstance(handoff, dict):
            raise KnxError("knx_correction_invalid")
        binding = handoff
    service = CorrectionService(store, shared.admin_reader(binding["draft_id"], target))
    source, selected = service.approved_selection(
        binding["draft_id"],
        config,
        target,
        binding["draft_revision"],
        binding["catalog_revision"],
        binding["manual_revision"],
        binding["approved_change_ids"],
        query=query,
    )
    choices: dict[int, dict[str, str]] = {}
    for row in selected:
        if (
            row["destination"] != "ets_export"
            or row["kind"] != "address"
            or row["operation"] != "set"
            or row["field"] not in {"name", "description"}
        ):
            raise KnxError("knx_export_selection_invalid")
        fields_by_address = choices.setdefault(row["address_id"], {})
        if row["field"] in fields_by_address:
            raise KnxError("knx_export_selection_invalid")
        fields_by_address[row["field"]] = row["value"]

    def fresh_source() -> None:
        if time.time() >= source["expires_at"]:
            raise KnxError("knx_draft_expired")

    fresh_source()
    authorize()
    fresh_source()
    project = source["project_binding"] or "local-explicit-proposal"
    if action == "knx_correction_xml_preview":
        result = exporter.preview(
            {
                "revision": source["catalog_revision"],
                "project_binding": project,
                "choices": [
                    {"address_id": number, "fields": fields} for number, fields in choices.items()
                ],
            },
            correction_handoff=binding,
        )
        authorize()
        fresh_source()
        return {"target": token, "correction_handoff": True, **result}
    result = exporter.download({**payload, "project_binding": project}, confirmed_handoff=True)
    authorize()
    fresh_source()
    return {"target": token, "correction_handoff": True, **result}
