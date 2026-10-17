"""Source-aware proposal planning; never applies local or project changes."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

from mcpserver.config import PluginConfig

from .catalog import labels_revision, manual_labels
from .correction_drafts import CorrectionDraftStore
from .correction_model import parse_correction_changes
from .import_repository import ImportRepository
from .model import KnxError
from .project_metadata import ProjectMetadata
from .store import KnxStore
from .xml_export import XmlCorrectionExport

if TYPE_CHECKING:
    from mcpserver.loxone.project.query import ProjectQuery


def project_binding(query: ProjectQuery) -> str:
    """A stand identifier is evidence identity, never authorization."""
    return hashlib.sha256(
        json.dumps(
            [
                query.view.snapshot.fingerprint,
                query.view.snapshot.model_version,
                query.view.snapshot.content_identity,
                query.view.mapping.structure_fingerprint,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class CorrectionService:
    """Adapters must authorize owner/target and any supplied project query freshly.

    Current project names are exposed only with that authorized query. Persisted
    proposals contain selected target values, not a copied project inventory.
    """

    def __init__(self, store: KnxStore, drafts: CorrectionDraftStore) -> None:
        self.store, self.drafts = store, drafts
        # Transient proposal batches must not create a second retained 16 MiB
        # cache beside the service-owned project metadata cache.
        self.metadata = ProjectMetadata(store.path, max_bytes=0)

    def plan(
        self,
        config: PluginConfig,
        target: str,
        revision: object,
        manual_revision: object,
        values: object,
        *,
        query: ProjectQuery | None = None,
    ) -> dict[str, Any]:
        changes = parse_correction_changes(values)
        expected_labels = labels_revision(config, target)
        if manual_revision != expected_labels:
            raise KnxError("knx_revision_conflict")
        with self.store.connection() as db:
            db.execute("BEGIN")
            self.store.check(db, target, revision)
            current = self.store.revision(db, target)
        numbers = {row["address_id"] for row in changes if row["kind"] == "address"}
        sources = self.metadata.lookup(target, current, numbers)
        labels = {
            (row["address_format"], row["prefix"]): row["label"]
            for row in manual_labels(config, target)
        }
        imported_labels = {
            (row["address_format"], row["prefix"]): row["label"]
            for row in (
                ImportRepository(self.store).selected_labels(target)
                if any(item["kind"] == "prefix" for item in changes)
                else []
            )
        }
        export_choices: dict[int, dict[str, str]] = {}
        project_used = False
        for row in changes:
            field = row["field"]
            if row["kind"] == "prefix":
                identity = (row["address_format"], row["prefix"])
                row["sources"] = {
                    "manual": {field: labels[identity]} if identity in labels else {},
                    "imported": {field: imported_labels[identity]}
                    if identity in imported_labels
                    else {},
                }
                continue
            number = row["address_id"]
            source = sources.get(number, {})
            # Only the changed field is retained; missing and deliberately empty
            # source values remain distinct through dictionary membership.
            row["sources"] = {
                name: {field: source[name][field]} if field in source.get(name, {}) else {}
                for name in ("imported", "manual")
            }
            if "project_object_id" in row:
                from mcpserver.loxone.project.ets_comparison import _object

                if query is None or query.graph_index is None:
                    raise KnxError("knx_project_evidence_required")
                if row["project_object_id"] not in query.graph_index.knx_by_address.get(number, ()):
                    raise KnxError("knx_project_evidence_changed")
                observed = _object(query, row["project_object_id"])
                name = "loxone_name" if field == "name" else "project_description"
                incomplete = (
                    not observed["name_complete"]
                    if field == "name"
                    else "description" in observed["truncated_fields"]
                )
                if (
                    row["operation"] != "set"
                    or incomplete
                    or observed[name] is None
                    or row["value"] != observed[name]
                ):
                    raise KnxError("knx_project_evidence_changed")
                project_used = True
            if row["destination"] == "ets_export":
                export_choices.setdefault(number, {})[field] = row["value"]
        binding = project_binding(query) if project_used and query is not None else None
        if export_choices:
            # Explicit preparation validates the existing exporter as one batch.
            # It must not evict an Admin's current ten-minute XML preview.
            XmlCorrectionExport(self.store, self.drafts, target).preview(
                {
                    "revision": current,
                    "project_binding": binding or "local-explicit-proposal",
                    "choices": [
                        {"address_id": number, "fields": fields}
                        for number, fields in export_choices.items()
                    ],
                },
                persist=False,
            )
        # A concurrent catalog change cannot silently bind new source values to
        # an earlier revision; draft persistence is a separate destination.
        with self.store.connection() as db:
            self.store.check(db, target, current)
        return {
            "catalog_revision": current,
            "manual_revision": expected_labels,
            "project_binding": binding,
            "changes": changes,
        }

    def inspect(
        self,
        identifier: object,
        config: PluginConfig,
        target: str,
        *,
        query: ProjectQuery | None = None,
    ) -> dict[str, Any]:
        draft = self.drafts.inspect_correction(identifier, target)
        with self.store.connection() as db:
            current = self.store.revision(db, target)
        bound = draft["project_binding"]
        draft.update(
            catalog_stale=current != draft["catalog_revision"],
            manual_stale=labels_revision(config, target) != draft["manual_revision"],
            project_status="not_required"
            if bound is None
            else "not_checked"
            if query is None
            else "current"
            if project_binding(query) == bound
            else "changed",
            applies_changes=False,
            exports_file=False,
        )
        return draft

    def review(
        self,
        identifier: object,
        config: PluginConfig,
        target: str,
        expected: object,
        catalog_revision: object,
        manual_revision: object,
        decisions: object,
        *,
        request_id: str,
        query: ProjectQuery | None = None,
    ) -> int:
        """Record explicit per-change decisions, without applying any destination.

        An unchecked project binding remains unchecked. Acceptance is the user's
        proposal decision, never a claim of fresh project authorization or an
        authorization to write local metadata or export a file.
        """
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 50:
            raise KnxError("knx_correction_invalid")
        selected: dict[str, str] = {}
        for decision in decisions:
            if (
                not isinstance(decision, dict)
                or set(decision) != {"change_id", "decision"}
                or not isinstance(decision["change_id"], str)
                or not re.fullmatch(r"[0-9a-f]{24}", decision["change_id"])
                or not isinstance(decision["decision"], str)
                or decision["decision"] not in {"accepted", "rejected", "proposed"}
                or decision["change_id"] in selected
            ):
                raise KnxError("knx_correction_invalid")
            selected[decision["change_id"]] = decision["decision"]
        operation = ["review", catalog_revision, manual_revision, decisions]
        previous = self.drafts.reconcile_update(identifier, target, expected, request_id, operation)
        if previous is not None:
            return previous
        draft = self._editable(
            identifier, config, target, expected, catalog_revision, manual_revision, query
        )
        if not selected.keys() <= {row["change_id"] for row in draft["changes"]}:
            raise KnxError("knx_correction_invalid")
        changes = [
            {**row, "decision": selected.get(row["change_id"], row["decision"])}
            for row in draft["changes"]
        ]
        return self._save_edit(
            identifier, target, expected, catalog_revision, changes, request_id, operation
        )

    def _editable(
        self,
        identifier: object,
        config: PluginConfig,
        target: str,
        expected: object,
        catalog_revision: object,
        manual_revision: object,
        query: ProjectQuery | None,
    ) -> dict[str, Any]:
        draft = self.inspect(identifier, config, target, query=query)
        if (
            type(expected) is not int
            or expected != draft["draft_revision"]
            or type(catalog_revision) is not int
            or catalog_revision != draft["catalog_revision"]
            or manual_revision != draft["manual_revision"]
            or draft["catalog_stale"]
            or draft["manual_stale"]
        ):
            raise KnxError("knx_revision_conflict")
        if draft["project_status"] == "changed":
            raise KnxError("knx_project_evidence_changed")
        return draft

    def approved_selection(
        self,
        identifier: object,
        config: PluginConfig,
        target: str,
        expected: object,
        catalog_revision: object,
        manual_revision: object,
        selected: object,
        *,
        query: ProjectQuery | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Resolve only explicit accepted IDs under fresh source/project bindings."""
        if (
            not isinstance(selected, list)
            or not 1 <= len(selected) <= 50
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{24}", item)
                for item in selected
            )
            or len(set(selected)) != len(selected)
        ):
            raise KnxError("knx_correction_invalid")
        draft = self._editable(
            identifier, config, target, expected, catalog_revision, manual_revision, query
        )
        if draft["project_status"] not in {"not_required", "current"}:
            raise KnxError("knx_project_evidence_required")
        rows = {row["change_id"]: row for row in draft["changes"]}
        if any(item not in rows or rows[item]["decision"] != "accepted" for item in selected):
            raise KnxError("knx_correction_not_accepted")
        return draft, [rows[item] for item in selected]

    def edit(
        self,
        identifier: object,
        config: PluginConfig,
        target: str,
        expected: object,
        catalog_revision: object,
        manual_revision: object,
        change_id: object,
        edit: object,
        *,
        request_id: str,
    ) -> int:
        """An explicit Admin edit keeps identity/source snapshots and resets consent.

        The new literal value is a user selection, not a verified Loxone value.
        The original project-stand binding is retained conservatively so later
        application still requires a fresh project check.
        """
        if (
            not isinstance(change_id, str)
            or not re.fullmatch(r"[0-9a-f]{24}", change_id)
            or not isinstance(edit, dict)
            or not edit.keys() <= {"operation", "value", "evidence_note"}
            or "operation" not in edit
        ):
            raise KnxError("knx_correction_invalid")
        operation = ["edit", catalog_revision, manual_revision, change_id, edit]
        previous = self.drafts.reconcile_update(identifier, target, expected, request_id, operation)
        if previous is not None:
            return previous
        draft = self._editable(
            identifier, config, target, expected, catalog_revision, manual_revision, None
        )
        existing = next((row for row in draft["changes"] if row["change_id"] == change_id), None)
        if existing is None:
            raise KnxError("knx_correction_invalid")
        raw = {key: existing[key] for key in ("destination", "kind", "address_format", "field")}
        identity = "address" if existing["kind"] == "address" else "prefix"
        if "evidence_note" in existing:
            raw["evidence_note"] = existing["evidence_note"]
        raw.update({identity: existing[identity], **edit})
        updated = parse_correction_changes([raw])[0]
        updated["sources"] = existing["sources"]
        if updated["destination"] == "ets_export":
            XmlCorrectionExport(self.store, self.drafts, target).preview(
                {
                    "revision": catalog_revision,
                    "project_binding": draft["project_binding"] or "local-explicit-proposal",
                    "choices": [
                        {
                            "address_id": updated["address_id"],
                            "fields": {updated["field"]: updated["value"]},
                        }
                    ],
                },
                persist=False,
            )
        changes = [updated if row["change_id"] == change_id else row for row in draft["changes"]]
        return self._save_edit(
            identifier, target, expected, catalog_revision, changes, request_id, operation
        )

    def _save_edit(
        self,
        identifier: object,
        target: str,
        expected: object,
        catalog_revision: object,
        changes: list[dict[str, Any]],
        request_id: str,
        operation: object,
    ) -> int:
        # Serialize against reimport/address writes until the draft update ends.
        # Config adapters separately hold the manual-label transaction lock.
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.check(db, target, catalog_revision)
            return self.drafts.update_correction(
                identifier,
                target,
                expected,
                changes,
                request_id=request_id,
                operation_payload=operation,
            )
