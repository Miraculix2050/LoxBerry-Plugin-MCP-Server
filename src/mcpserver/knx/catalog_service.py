"""Preview and explicit application of revision-bound ETS imports."""

from __future__ import annotations

import hashlib
import json
import secrets
from contextlib import closing
from typing import Any

from .csv_adapter import parse_csv
from .drafts import DraftStore
from .import_model import MAX_GROUPS, ImportDocument, ImportSelection
from .import_repository import ImportRepository
from .import_service import select_candidates
from .model import MAX_ADDRESSES, KnxError, text
from .xml_adapter import parse_xml


def group_identity(fmt: str, prefix: str) -> str:
    return f"group:{fmt}:{prefix}"


class CatalogService:
    def __init__(
        self,
        repository: ImportRepository,
        drafts: DraftStore,
        target: str,
        manual_labels: list[dict[str, str]],
    ) -> None:
        self.repository = repository
        self.drafts = drafts
        self.target = target
        self.manual_labels = manual_labels

    def manual_revision(self) -> str:
        return hashlib.sha256(json.dumps(self.manual_labels, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def parse(raw: bytes, options: dict[str, Any]) -> ImportDocument:
        kind = options.get("file_format")
        if kind == "auto":
            prefix = raw.removeprefix(b"\xef\xbb\xbf").lstrip(b" \r\n\t")
            kind = "xml" if prefix.startswith(b"<") else "csv"
        if kind not in ("xml", "csv"):
            raise KnxError("knx_import_format_unsupported")
        parser = parse_xml if kind == "xml" else parse_csv
        return parser(
            raw, encoding=options["encoding"], address_format=options.get("address_format")
        )

    def create(
        self,
        raw: bytes,
        *,
        encoding: str,
        complete_export: bool,
        address_format: str | None = None,
        file_format: str = "xml",
    ) -> dict[str, Any]:
        if type(complete_export) is not bool:
            raise KnxError("knx_scope_invalid")
        if address_format not in (None, "two_level", "three_level"):
            raise KnxError("knx_format_invalid")
        options: dict[str, Any] = {
            "file_format": file_format,
            "encoding": encoding,
            "address_format": address_format,
            "complete_export": complete_export,
            "mode": "merge",
            "choices": {},
            "manual_revision": self.manual_revision(),
            "preview_token": secrets.token_hex(16),
        }
        document = self.parse(raw, options)
        options["file_format"] = document.file_format
        snapshot = self.repository.snapshot(self.target)
        options["selected_groups"] = [
            group_identity(*key) for key, group in snapshot["groups"].items() if group["selected"]
        ]
        selection = select_candidates(document)
        prepared = self.prepare(document, selection, snapshot, options)
        identifier = self.drafts.create(self.target, snapshot["revision"], raw, options)
        return self.response(identifier, options, document, selection, prepared, offset=0)

    def preview(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.repository.snapshot(self.target)
        raw, options = self.drafts.load(identifier, self.target, snapshot["revision"])
        if options.get("draft_slot", "import") != "import":
            raise KnxError("knx_draft_invalid")
        if options.get("manual_revision") != self.manual_revision():
            raise KnxError("knx_revision_conflict")
        if not payload.keys() <= {
            "choices",
            "selected_groups",
            "mode",
            "orphan_name_policy",
            "offset",
            "conflict_offset",
        }:
            raise KnxError("knx_preview_invalid")
        previous_mode = options["mode"]
        options.update(
            {
                key: value
                for key, value in payload.items()
                if key not in {"offset", "conflict_offset"}
            }
        )
        document = self.parse(raw, options)
        if previous_mode != "replace" and payload.get("mode") == "replace":
            available = {group_identity(row.address_format, row.prefix) for row in document.groups}
            previous_groups = {group_identity(*key) for key in snapshot["groups"]}
            selected = options["selected_groups"]
            if (
                not isinstance(selected, list)
                or len(selected) > 128
                or any(
                    not isinstance(key, str) or key not in available | previous_groups
                    for key in selected
                )
                or len(set(selected)) != len(selected)
            ):
                raise KnxError("knx_label_selection_invalid")
            options["selected_groups"] = [key for key in selected if key in available]
        selection = select_candidates(document, options["choices"])
        offset = payload.get("offset", 0)
        if type(offset) is not int or not 0 <= offset <= MAX_ADDRESSES:
            raise KnxError("knx_page_invalid")
        conflict_offset = payload.get("conflict_offset", 0)
        if (
            type(conflict_offset) is not int
            or not 0 <= conflict_offset <= MAX_ADDRESSES + MAX_GROUPS
        ):
            raise KnxError("knx_page_invalid")
        prepared = self.prepare(document, selection, snapshot, options, offset=offset)
        options["preview_token"] = secrets.token_hex(16)
        self.drafts.update(identifier, options)
        return self.response(
            identifier,
            options,
            document,
            selection,
            prepared,
            offset=offset,
            conflict_offset=conflict_offset,
        )

    def apply(self, identifier: str, token: object) -> dict[str, Any]:
        snapshot = self.repository.snapshot(self.target)
        raw, options = self.drafts.load(identifier, self.target, snapshot["revision"])
        if options.get("draft_slot", "import") != "import":
            raise KnxError("knx_draft_invalid")
        if options.get("manual_revision") != self.manual_revision():
            raise KnxError("knx_revision_conflict")
        if not isinstance(token, str) or not secrets.compare_digest(
            token, options.get("preview_token", "")
        ):
            raise KnxError("knx_preview_changed")
        document = self.parse(raw, options)
        selection = select_candidates(document, options["choices"])
        if selection.conflicts:
            raise KnxError("knx_import_conflicts")
        prepared = self.prepare(document, selection, snapshot, options)
        if prepared["name_policy_required"]:
            raise KnxError("knx_orphan_name_policy_required")
        if prepared["invalid_labels"]:
            raise KnxError("knx_label_selection_invalid")
        chosen = {
            (key.split(":", 2)[1], key.split(":", 2)[2]) for key in options["selected_groups"]
        }
        revision = self.repository.apply(
            self.target,
            snapshot["revision"],
            document,
            selection,
            chosen,
            {
                "complete_export": options["complete_export"],
                "digest": hashlib.sha256(raw).hexdigest(),
                "file_format": document.file_format,
                "encoding": document.encoding,
            },
            mode=options["mode"],
            orphan_name_policy=options.get("orphan_name_policy"),
        )
        cleanup_pending = False
        try:
            self.drafts.discard(identifier)
        except (KnxError, OSError):
            # The catalog transaction has committed. Never report it as a rejected write.
            cleanup_pending = True
        return {"revision": revision, "draft_cleanup_pending": cleanup_pending}

    def prepare(
        self,
        document: ImportDocument,
        selection: ImportSelection,
        snapshot: dict[str, Any],
        options: dict[str, Any],
        *,
        offset: int = 0,
    ) -> dict[str, Any]:
        if options["mode"] not in {"merge", "replace"} or (
            options["mode"] == "replace" and options["complete_export"] is not True
        ):
            raise KnxError("knx_import_mode_invalid")
        name_policy = options.get("orphan_name_policy")
        if name_policy not in {None, "keep_unknown", "retain_import_name"}:
            raise KnxError("knx_orphan_name_policy_invalid")
        existing = snapshot["addresses"]
        additions = 0
        changes = []
        changed_count = 0
        previous_rows = self.repository.address_rows(
            self.target, [row.number for row in selection.addresses], snapshot["revision"]
        )
        # Explicitly close read transactions on validation failure as well as exhaustion.
        with closing(previous_rows):
            previous = next(previous_rows, None)
            for record in selection.addresses:
                old = previous[1] if previous is not None and previous[0] == record.number else None
                if old is None:
                    additions += 1
                changed_fields = sorted(
                    key
                    for key in set(old["imported"] if old else {}) | record.fields.keys()
                    if old is None
                    or key not in old["imported"]
                    or key not in record.fields
                    or old["imported"][key] != record.fields[key]
                )
                if old is None or changed_fields or old["address_format"] != record.address_format:
                    if offset <= changed_count < offset + 50:
                        changes.append(
                            {
                                "address": record.original,
                                "address_id": record.number,
                                "kind": "added" if old is None else "changed",
                                "fields": changed_fields,
                                "old_imported": old["imported"] if old else {},
                                "new_imported": record.fields,
                                "overrides": old["overrides"] if old else {},
                            }
                        )
                    changed_count += 1
                if old is not None:
                    previous = next(previous_rows, None)
        removals = preserved = nameless = 0
        if options["mode"] == "replace":
            absent = sorted(set(existing) - {row.number for row in document.addresses})
            with closing(
                self.repository.address_rows(self.target, absent, snapshot["revision"])
            ) as rows:
                for number, old in rows:
                    if not old["imported"]:
                        continue
                    if old["overrides"]:
                        preserved += 1
                        if "name" not in old["overrides"]:
                            nameless += 1
                        overrides = dict(old["overrides"])
                        if name_policy == "retain_import_name" and "name" not in overrides:
                            overrides["name"] = old["imported"]["name"]
                    else:
                        removals += 1
                        overrides = {}
                    if offset <= changed_count < offset + 50:
                        changes.append(
                            {
                                "address": old["address"],
                                "address_id": number,
                                "kind": "preserved" if overrides else "removed",
                                "fields": sorted(old["imported"]),
                                "old_imported": old["imported"],
                                "new_imported": {},
                                "overrides": overrides,
                            }
                        )
                    changed_count += 1
        if len(existing) + additions - removals > MAX_ADDRESSES:
            raise KnxError("knx_address_limit")
        groups = {
            group_identity(*key): group["fields"]
            for key, group in snapshot["groups"].items()
            if options["mode"] == "merge"
        }
        groups.update(
            {group_identity(row.address_format, row.prefix): row.fields for row in selection.groups}
        )
        if len(groups) > MAX_GROUPS:
            raise KnxError("knx_group_limit")
        selected = options.get("selected_groups")
        if (
            not isinstance(selected, list)
            or len(selected) > 128
            or any(not isinstance(key, str) or key not in groups for key in selected)
            or len(set(selected)) != len(selected)
        ):
            raise KnxError("knx_label_selection_invalid")
        active = {
            group_identity(row["address_format"], row["prefix"]) for row in self.manual_labels
        }
        invalid_labels = []
        for identity in selected:
            try:
                text(groups[identity]["name"], 80, empty=False)
            except KnxError:
                # Reimport may lengthen a previously selected group name. Allow a
                # non-mutating preview so the administrator can explicitly deselect it.
                invalid_labels.append(identity)
            active.add(identity)
        if len(active) > 128:
            raise KnxError("knx_label_limit")
        included_groups = {
            group_identity(row.address_format, row.prefix) for row in selection.groups
        }
        return {
            "revision": snapshot["revision"],
            "additions": additions,
            "updates": changed_count - additions - removals - preserved,
            "removals": removals,
            "preserved_overrides": preserved,
            "nameless_overrides": nameless,
            "name_policy_required": nameless > 0 and name_policy is None,
            "orphan_name_policy": name_policy,
            "invalid_labels": invalid_labels,
            "changes_count": changed_count,
            "changes": changes,
            "selected_groups": selected,
            "manual_labels": self.manual_labels,
            "groups": [
                {
                    "identity": identity,
                    "prefix": identity.split(":", 2)[2],
                    "address_format": identity.split(":", 2)[1],
                    "fields": fields,
                    "selected": identity in selected,
                    "included_in_file": identity in included_groups,
                }
                for identity, fields in sorted(groups.items())
            ],
        }

    @staticmethod
    def response(
        identifier: str,
        options: dict[str, Any],
        document: ImportDocument,
        selection: ImportSelection,
        prepared: dict[str, Any],
        *,
        offset: int,
        conflict_offset: int = 0,
    ) -> dict[str, Any]:
        return {
            **{key: value for key, value in prepared.items() if key not in {"changes", "groups"}},
            "draft_id": identifier,
            "preview_token": options["preview_token"],
            "file_format": document.file_format,
            "encoding": document.encoding,
            "layout": document.source.get("layout", ""),
            "address_format": document.address_format,
            "complete_export": options["complete_export"],
            "mode": options["mode"],
            "addresses": len({row.number for row in document.addresses}),
            "groups_count": len({(row.address_format, row.prefix) for row in document.groups}),
            "groups_total": len(prepared["groups"]),
            "merged_duplicates": selection.merged_duplicates,
            "conflict_count": len(selection.conflicts),
            "conflicts": selection.conflicts[conflict_offset : conflict_offset + 5],
            "conflict_offset": conflict_offset,
            "has_more_conflicts": conflict_offset + 5 < len(selection.conflicts),
            "changes": prepared["changes"],
            "groups": prepared["groups"][offset : offset + 50],
            "offset": offset,
            "has_more": offset + 50 < max(prepared["changes_count"], len(prepared["groups"])),
        }
