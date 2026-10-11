"""Source-aware proposal planning; never applies local or project changes."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mcpserver.config import PluginConfig
from mcpserver.loxone.project.ets_comparison import _object
from mcpserver.loxone.project.query import ProjectQuery

from .catalog import labels_revision, manual_labels
from .correction_drafts import CorrectionDraftStore
from .correction_model import parse_correction_changes
from .import_repository import ImportRepository
from .model import KnxError
from .project_metadata import ProjectMetadata
from .store import KnxStore
from .xml_export import XmlCorrectionExport


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
