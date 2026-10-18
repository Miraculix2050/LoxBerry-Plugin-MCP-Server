"""Narrow administrative metadata actions; no Miniserver operations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.loxone.endpoint import MiniserverEndpoint
from mcpserver.loxone.project.taxonomy import parse_taxonomy
from mcpserver.persistence import PersistenceUncertain

from .model import MAX_FILE_BYTES, KnxError

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcpserver.loxone.project.query import ProjectQuery


def validate_active_labels(config: PluginConfig) -> None:
    """Keep legacy configuration writes within the shared active-label bound."""
    from .import_repository import ImportRepository
    from .store import KnxStore

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


def dispatch_knx(
    action: str,
    payload: object,
    config_store: AtomicConfigStore,
    *,
    query: ProjectQuery | None = None,
    authorize_effect: Callable[[], object] | None = None,
    admin_session: str | None = None,
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    from mcpserver.admin import AdminError

    allowed = {
        "knx_page",
        "knx_groups_page",
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
        "knx_compare_load",
        "knx_compare_page",
        "knx_compare_discard",
        "knx_xml_preview",
        "knx_xml_download",
        "knx_xml_discard",
        "knx_read_page",
        "knx_read_enable",
        "knx_read_grant",
        "knx_read_revoke",
        "knx_drafts_page",
        "knx_drafts_enable",
        "knx_drafts_grant",
        "knx_drafts_revoke",
        "knx_write_page",
        "knx_write_enable",
        "knx_write_grant",
        "knx_write_revoke",
        "knx_correction_page",
        "knx_correction_inspect",
        "knx_correction_review",
        "knx_correction_edit",
        "knx_correction_manage",
        "knx_correction_apply",
        "knx_correction_xml_preview",
        "knx_correction_xml_download",
        "knx_project_page",
    }
    if action not in allowed or not isinstance(payload, dict):
        raise AdminError("Unsupported KNX action")
    outcome = "rejected"
    try:
        if action == "knx_project_page" and (
            query is not None or not os.environ.get("HTTP_X_LOXONE_AUTHORIZATION")
        ):
            raise AdminError("Project evidence required", code="knx_project_evidence_required")
        if (
            query is None
            and action
            in {
                "knx_correction_apply",
                "knx_correction_xml_preview",
                "knx_correction_xml_download",
                "knx_project_page",
            }
            and bool(os.environ.get("HTTP_X_LOXONE_AUTHORIZATION", ""))
        ):
            from .admin_bridge import forward

            result = forward(action, payload, config_store)
        else:
            result = config_store.transaction(
                lambda config, save: _run(
                    action,
                    payload,
                    config,
                    save,
                    query=query,
                    authorize_effect=authorize_effect,
                    admin_session=admin_session,
                    metadata_path=metadata_path,
                )
            )
        outcome = (
            result.get("outcome", "completed") if action == "knx_correction_apply" else "completed"
        )
        return result
    except PersistenceUncertain:
        outcome = "uncertain"
        raise
    except AdminError as exc:
        if exc.code in {"persistence_uncertain", "write_outcome_uncertain"} or (
            action == "knx_correction_apply"
            and payload.get("action") == "apply"
            and exc.code == "knx_storage_failed"
        ):
            outcome = "uncertain"
        raise
    except KnxError as exc:
        if exc.code == "write_outcome_uncertain" or (
            action == "knx_correction_apply"
            and payload.get("action") == "apply"
            and exc.code == "knx_storage_failed"
        ):
            outcome = "uncertain"
        raise AdminError("KNX operation rejected", code=exc.code) from None
    finally:
        if action in {
            "knx_correction_review",
            "knx_correction_edit",
            "knx_correction_manage",
            "knx_correction_apply",
            "knx_correction_xml_preview",
            "knx_correction_xml_download",
        }:
            LOGGER.info(
                "component=knx_draft_admin_audit action=%s mode=%s outcome=%s",
                action,
                payload.get("action")
                if payload.get("action") in ("apply", "reconcile")
                else "draft",
                outcome,
                extra={"mcp_audit": True},
            )


def _run(
    action: str,
    payload: dict[str, Any],
    config: PluginConfig,
    save: Callable[[PluginConfig], None],
    *,
    query: ProjectQuery | None = None,
    authorize_effect: Callable[[], object] | None = None,
    admin_session: str | None = None,
    metadata_path: Path | None = None,
    read_auth: Any = None,
) -> dict[str, Any]:
    from mcpserver.admin import AdminError

    native_session: str = os.environ.get("MCPSERVER_KNX_ADMIN_SESSION", "")
    session_value = admin_session if admin_session is not None else native_session

    if not config.loxone_endpoint:
        raise AdminError("A configured Miniserver is required", code="knx_target_missing")
    target = MiniserverEndpoint.parse(config.loxone_endpoint).origin
    token = hashlib.sha256(target.encode()).hexdigest()
    if (
        action == "knx_page"
        and "include_sections" in payload
        and not isinstance(payload["include_sections"], bool)
    ):
        raise KnxError("knx_page_invalid")
    if (
        action == "knx_page"
        and "initial_groups" in payload
        and (
            not payload.get("include_sections")
            or not isinstance(payload["initial_groups"], dict)
            or not payload["initial_groups"].keys() <= {"sort"}
        )
    ):
        raise KnxError("knx_page_invalid")
    if (
        action == "knx_page"
        and "initial_correction" in payload
        and (
            not payload.get("include_sections")
            or not isinstance(payload["initial_correction"], dict)
            or not payload["initial_correction"].keys() <= {"target", "draft_id", "offset", "sort"}
        )
    ):
        raise KnxError("knx_page_invalid")
    if (
        action
        not in {
            "knx_page",
            "knx_export",
            "knx_read_page",
            "knx_drafts_page",
            "knx_write_page",
            "knx_correction_page",
        }
        and payload.get("target") != token
    ):
        raise AdminError("KNX target changed; reload", code="knx_target_conflict")
    if (
        action
        in {
            "knx_page",
            "knx_export",
            "knx_read_page",
            "knx_drafts_page",
            "knx_write_page",
            "knx_correction_page",
        }
        and "target" in payload
        and payload["target"] != token
    ):
        raise AdminError("KNX target changed; reload", code="knx_target_conflict")
    if action.startswith(("knx_read_", "knx_drafts_", "knx_write_")):
        from mcpserver.admin import _auth_store

        from .read_admin import DRAFT_POLICY, READ_POLICY, WRITE_POLICY, dispatch

        policy = {"knx_read": READ_POLICY, "knx_drafts": DRAFT_POLICY, "knx_write": WRITE_POLICY}[
            action.rsplit("_", 1)[0]
        ]
        if action == "knx_read_page" and "include_delegations" in payload:
            from .read_admin import _ReadPageAuthSnapshot

            if type(payload["include_delegations"]) is not bool:
                raise KnxError("knx_delegation_invalid")
            request = {key: value for key, value in payload.items() if key != "include_delegations"}
            if not request.keys() <= {"target"}:
                raise KnxError("knx_delegation_invalid")
            view = _ReadPageAuthSnapshot(_auth_store().snapshot())
            if not payload["include_delegations"]:
                return {
                    **dispatch(action, request, config, save, view, target, policy),
                    "target": token,
                }
            delegations: dict[str, Any] = {}
            for selected in (READ_POLICY, DRAFT_POLICY, WRITE_POLICY):
                selected_action = f"{selected.prefix}_page"
                try:
                    delegations[selected_action] = {
                        "ok": True,
                        "data": {
                            **dispatch(
                                selected_action,
                                request,
                                config,
                                save,
                                view,
                                target,
                                selected,
                            ),
                            "target": token,
                        },
                    }
                except (AdminError, KnxError) as exc:
                    delegations[selected_action] = {"ok": False, "error": {"code": exc.code}}
                except Exception:
                    delegations[selected_action] = {
                        "ok": False,
                        "error": {"code": "internal_error"},
                    }
            primary = delegations[action]
            data = dict(primary["data"]) if primary["ok"] else {"target": token}
            return {**data, "delegations": delegations}
        return {
            **dispatch(action, payload, config, save, read_auth or _auth_store(), target, policy),
            "target": token,
        }
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
        "knx_compare_load": {
            "target",
            "file",
            "side",
            "encoding",
            "complete_export",
            "address_format",
            "file_format",
        },
        "knx_compare_page": {
            "target",
            "left_id",
            "right_id",
            "revision",
            "taxonomy_revision",
            "offset",
            "sort",
        },
        "knx_compare_discard": {"target", "draft_id"},
        "knx_xml_preview": {"target", "revision", "choices", "project_binding"},
        "knx_xml_download": {
            "target",
            "revision",
            "draft_id",
            "project_binding",
            "confirmed_experimental",
        },
        "knx_xml_discard": {"target", "draft_id"},
    }
    if action in import_fields and not payload.keys() <= import_fields[action]:
        raise KnxError("knx_preview_invalid")
    data_root = (
        str(metadata_path.parent.parent) if metadata_path is not None else os.getenv("LBPDATA", "")
    )
    if not data_root or not Path(data_root).is_absolute():
        raise AdminError("Plugin data directory unavailable")
    from .store import KnxStore

    store = KnxStore(metadata_path or Path(data_root) / "knx" / "metadata.sqlite3")
    if action in {"knx_correction_xml_preview", "knx_correction_xml_download"}:
        from .admin_export import correction_export

        return correction_export(
            action,
            payload,
            config,
            store,
            target,
            token,
            session_value,
            query=query,
            authorize=authorize_effect or (lambda: None),
        )
    if action in {
        "knx_correction_page",
        "knx_correction_inspect",
        "knx_correction_review",
        "knx_correction_edit",
        "knx_correction_manage",
        "knx_correction_apply",
    }:
        from .correction_drafts import CorrectionDraftStore, _identifier

        fields = {"target", "draft_id", "draft_revision", "offset", "detail", "sort"}
        if action == "knx_correction_manage":
            fields = {"target", "draft_id", "draft_revision", "operation", "request_id", "metadata"}
        if action == "knx_correction_apply":
            fields = {
                "target",
                "draft_id",
                "draft_revision",
                "catalog_revision",
                "manual_revision",
                "request_id",
                "approved_change_ids",
                "storage",
                "confirmed",
                "action",
            }
        if action in {"knx_correction_review", "knx_correction_edit"}:
            fields = {
                "target",
                "draft_id",
                "draft_revision",
                "catalog_revision",
                "manual_revision",
                "request_id",
            }
            fields |= {"decisions"} if action == "knx_correction_review" else {"change_id", "edit"}
        if not payload.keys() <= fields:
            raise KnxError("knx_correction_invalid")
        corrections = CorrectionDraftStore(
            Path(data_root) / "knx" / "drafts.sqlite3",
            session_value,
        )
        if action == "knx_correction_page":
            return {"target": token, "drafts": corrections.list_admin(target)}
        if action == "knx_correction_manage" and payload.get("operation") == "delete":
            if "metadata" in payload:
                raise KnxError("knx_correction_invalid")
            corrections.delete_admin(
                payload.get("draft_id"),
                target,
                payload.get("draft_revision"),
                payload.get("request_id"),
            )
            return {"target": token, "managed": True}
        from .correction_projection import project_draft
        from .correction_service import CorrectionService

        correction_id = _identifier(payload.get("draft_id"))
        correction_service = CorrectionService(
            store,
            corrections
            if action == "knx_correction_apply" and payload.get("action") == "reconcile"
            else corrections.admin_reader(correction_id, target),
        )
        if action == "knx_correction_manage":
            correction_service.drafts.manage(
                correction_id,
                target,
                payload.get("draft_revision"),
                payload.get("operation"),
                payload.get("request_id"),
                payload.get("metadata"),
            )
            return {"target": token, "managed": True}
        if action == "knx_correction_apply":
            from .correction_apply import CorrectionApply

            if payload.get("confirmed") is not True or payload.get("action") not in (
                "apply",
                "reconcile",
            ):
                raise KnxError("knx_correction_invalid")
            # Admin authentication is supplied by Apache/CGI, independently of
            # delegated MCP grants. Scope receipts to this Admin session and the
            # selected draft ID. Receipt lookup remains possible after draft
            # expiry; never accept ownership from the browser.
            owner = hashlib.sha256(
                ("knx-admin-apply-v1:" + corrections.session + ":" + correction_id).encode()
            ).hexdigest()
            result = CorrectionApply(correction_service, owner).execute(
                config,
                target,
                payload,
                reconcile=payload["action"] == "reconcile",
                authorize_effect=authorize_effect or (lambda: None),
                save_config=save,
                query=query,
            )
            return {"target": token, **result}
        if action in {"knx_correction_review", "knx_correction_edit"}:
            request_id = payload.get("request_id")
            if not isinstance(request_id, str):
                raise KnxError("knx_correction_invalid")
            args = (
                correction_id,
                config,
                target,
                payload.get("draft_revision"),
                payload.get("catalog_revision"),
                payload.get("manual_revision"),
            )
            if action == "knx_correction_review":
                revision = correction_service.review(
                    *args, payload.get("decisions"), request_id=request_id
                )
            else:
                revision = correction_service.edit(
                    *args,
                    payload.get("change_id"),
                    payload.get("edit"),
                    request_id=request_id,
                )
            result = correction_service.drafts.inspect_correction(correction_id, target)
            return {
                "target": token,
                "draft_id": correction_id,
                "draft_revision": result["draft_revision"],
                "operation_revision": revision,
                "expires_at": result["expires_at"],
                "applies_changes": False,
                "exports_file": False,
            }
        offset = payload.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= 50:
            raise KnxError("knx_correction_invalid")
        detail = payload.get("detail", False)
        if type(detail) is not bool:
            raise KnxError("knx_correction_invalid")
        draft = correction_service.inspect(correction_id, config, target)
        if (
            type(payload.get("draft_revision")) is not int
            or payload["draft_revision"] != draft["draft_revision"]
        ):
            raise KnxError("knx_revision_conflict")
        return {
            "target": token,
            **project_draft(
                {"target_id": token, "draft": draft},
                offset,
                1 if detail else 10,
                detail,
                payload.get("sort") if not detail else None,
            ),
        }
    from .import_repository import ImportRepository

    repository = ImportRepository(store)
    entries = config.knx_address_taxonomy if config.knx_address_taxonomy_endpoint == target else ()
    taxonomy_document = [
        {"prefix": e.prefix, "label": e.label, "address_format": e.address_format} for e in entries
    ]
    taxonomy_revision = hashlib.sha256(
        json.dumps(taxonomy_document, sort_keys=True).encode()
    ).hexdigest()
    if action == "knx_groups_page":
        if not payload.keys() <= {
            "target",
            "offset",
            "query_revision",
            "taxonomy_revision",
            "query",
            "sort",
        }:
            raise KnxError("knx_page_invalid")
        if payload.get("offset", 0) and (
            "query_revision" not in payload or payload.get("taxonomy_revision") != taxonomy_revision
        ):
            raise KnxError("knx_revision_conflict")
        return {
            "target": token,
            "taxonomy": taxonomy_document,
            "taxonomy_revision": taxonomy_revision,
            **store.admin_groups(
                target,
                taxonomy_document,
                offset=payload.get("offset", 0),
                expected=payload.get("query_revision"),
                query=payload.get("query", ""),
                table_sort=payload.get("sort"),
            ),
        }
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
    if action.startswith("knx_xml_"):
        from .drafts import DraftStore
        from .xml_export import XmlCorrectionExport

        drafts = DraftStore(
            Path(data_root) / "knx" / "drafts.sqlite3", os.getenv("MCPSERVER_KNX_ADMIN_SESSION", "")
        )
        exporter = XmlCorrectionExport(store, drafts, target)
        if action == "knx_xml_preview":
            return {**exporter.preview(payload), "target": token}
        if action == "knx_xml_download":
            return {**exporter.download(payload), "target": token}
        if "draft_id" in payload:
            drafts.discard(payload["draft_id"], slots=("xml_export",))
        else:
            drafts.discard_xml_export()
        return {"discarded": True}
    if action.startswith("knx_compare_"):
        from .drafts import DraftStore
        from .file_comparison import FileComparison

        drafts = DraftStore(
            Path(data_root) / "knx" / "drafts.sqlite3", os.getenv("MCPSERVER_KNX_ADMIN_SESSION", "")
        )
        comparison_service = FileComparison(store, drafts, target, taxonomy_document)
        if action == "knx_compare_load":
            encoded = payload.get("file")
            if not isinstance(encoded, str) or len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
                raise KnxError("knx_file_limit")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise KnxError("knx_file_invalid") from None
            return {
                **comparison_service.load(
                    raw,
                    payload.get("side"),
                    {
                        "encoding": payload.get("encoding", "auto"),
                        "file_format": payload.get("file_format", "auto"),
                        "address_format": payload.get("address_format"),
                        "complete_export": payload.get("complete_export", False),
                    },
                ),
                "target": token,
            }
        if action == "knx_compare_discard":
            if "draft_id" in payload:
                drafts.discard(payload["draft_id"], slots=("compare_left", "compare_right"))
            else:
                drafts.discard_comparison()
            return {"discarded": True}
        return {**comparison_service.page(payload), "target": token}
    if action.startswith("knx_import_"):
        from .catalog_service import CatalogService
        from .drafts import DraftStore

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
            **store.page(target, include_groups=True),
            "target": token,
            "target_display": target,
            "taxonomy": taxonomy_document,
            "taxonomy_revision": taxonomy_revision,
            "imported_labels": repository.selected_labels(target),
            **outcome,
        }
    try:
        if action == "knx_export":
            return {
                "document": store.export(
                    target,
                    payload.get("offset", 0),
                    filters=payload.get("filters"),
                    expected=payload.get("query_revision"),
                    table_sort=payload.get("sort"),
                ),
                "target": token,
            }
        if action == "knx_preview":
            return {**store.preview(target, payload.get("document")), "target": token}
        if action == "knx_restore":
            store.restore(target, payload.get("revision"), payload.get("document"))
        elif action == "knx_put":
            store.put(target, payload.get("revision"), payload.get("record"))
        elif action == "knx_delete":
            store.delete(target, payload.get("revision"), payload.get("address_id"))
        page = store.page(
            target,
            payload.get("offset", 0),
            include_groups=True,
            filters=payload.get("filters") if action == "knx_page" else None,
            expected=payload.get("query_revision") if action == "knx_page" else None,
            table_sort=payload.get("sort"),
        )
    except KnxError as exc:
        raise AdminError("KNX operation rejected", code=exc.code) from None
    result = {
        **page,
        "target": token,
        "target_display": target,
        "taxonomy": taxonomy_document,
        "taxonomy_revision": taxonomy_revision,
        "imported_labels": repository.selected_labels(target),
    }
    if action == "knx_page" and payload.get("include_sections"):
        sections: dict[str, Any] = {}
        # One isolated, validated read per request; never retained across requests.
        from mcpserver.admin import _auth_store

        from .read_admin import _ReadPageAuthSnapshot

        try:
            read_auth = _ReadPageAuthSnapshot(_auth_store().snapshot())
        except Exception:
            read_auth = None
        for section_action in (
            "knx_read_page",
            "knx_drafts_page",
            "knx_write_page",
            "knx_correction_page",
            *(("knx_groups_page",) if "initial_groups" in payload else ()),
            *(("knx_correction_inspect",) if "initial_correction" in payload else ()),
        ):
            try:
                section_payload: dict[str, Any] = {"target": token}
                if section_action == "knx_groups_page":
                    section_payload.update(payload["initial_groups"])
                if section_action == "knx_correction_inspect":
                    section_payload = dict(payload["initial_correction"])
                    listed = sections["knx_correction_page"]
                    if not listed["ok"]:
                        raise KnxError("knx_draft_unavailable")
                    selected_draft: dict[str, Any] | None = next(
                        (
                            item
                            for item in listed["data"]["drafts"]
                            if item["draft_id"] == section_payload.get("draft_id")
                        ),
                        None,
                    )
                    if selected_draft is None:
                        raise KnxError("knx_draft_unavailable")
                    section_payload["draft_revision"] = selected_draft["draft_revision"]
                    offset = section_payload.get("offset", 0)
                    if type(offset) is not int or not 0 <= offset < 50:
                        raise KnxError("knx_correction_invalid")
                    section_payload["offset"] = (
                        offset if offset < selected_draft["change_count"] else 0
                    )
                sections[section_action] = {
                    "ok": True,
                    "data": _run(
                        section_action, section_payload, config, save, read_auth=read_auth
                    ),
                }
                if section_action == "knx_correction_inspect":
                    sections[section_action]["request"] = {
                        key: section_payload.get(key)
                        for key in ("target", "draft_id", "offset", "sort")
                    }
            except (AdminError, KnxError) as exc:
                LOGGER.warning(
                    "component=knx_initial_section action=%s outcome=rejected code=%s",
                    section_action,
                    exc.code,
                )
                sections[section_action] = {"ok": False, "error": {"code": exc.code}}
            except Exception:
                LOGGER.warning(
                    "component=knx_initial_section action=%s outcome=rejected code=internal_error",
                    section_action,
                )
                sections[section_action] = {"ok": False, "error": {"code": "internal_error"}}
        result["sections"] = sections
    return result
