"""Experimental, selected-address XML serializer; never writes catalog data."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, cast

from .drafts import DraftStore
from .model import MAX_FILE_BYTES, KnxError, address, text
from .store import KnxStore
from .xml_adapter import NAMESPACE, TAG, parse_xml

MAX_EXPORT_SELECTION = 50


def _attributes(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or len(value) > 64:
        raise KnxError("knx_export_source_unavailable")
    return {text(key, 255, empty=False): text(item, 4096) for key, item in value.items()}


def _decode(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except ValueError:
        raise KnxError("knx_storage_failed") from None
    if not isinstance(result, dict):
        raise KnxError("knx_storage_failed")
    return result


class XmlCorrectionExport:
    def __init__(self, store: KnxStore, drafts: DraftStore, target: str) -> None:
        self.store, self.drafts, self.target = store, drafts, target

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        expected = payload.get("revision")
        choices = payload.get("choices")
        binding = text(payload.get("project_binding"), 4096, empty=False)
        if not isinstance(choices, list) or not 1 <= len(choices) <= MAX_EXPORT_SELECTION:
            raise KnxError("knx_export_selection_invalid")
        requested: dict[int, dict[str, str]] = {}
        for item in choices:
            if not isinstance(item, dict) or set(item) != {"address_id", "fields"}:
                raise KnxError("knx_export_selection_invalid")
            number, fields = item["address_id"], item["fields"]
            if type(number) is not int or not 0 <= number < 65536 or number in requested:
                raise KnxError("knx_export_selection_invalid")
            if not isinstance(fields, dict) or not fields.keys() <= {"name", "description"}:
                raise KnxError("knx_export_selection_invalid")
            # Empty descriptions remain disabled until actual ETS acceptance.
            requested[number] = {
                key: text(value, 255 if key == "name" else 4096, empty=False)
                for key, value in fields.items()
            }
        with self.store.connection() as db:
            db.execute("BEGIN")
            self.store.check(db, self.target, expected)
            expected = self.store.revision(db, self.target)
            state_row = db.execute(
                "SELECT information FROM import_state WHERE target=?", (self.target,)
            ).fetchone()
            if state_row is None:
                raise KnxError("knx_export_source_unavailable")
            state = _decode(state_row[0])
            document = state.get("document", {})
            if not isinstance(document, dict):
                raise KnxError("knx_export_source_unavailable")
            # Interior comment positions cannot be reconstructed safely after
            # omitting siblings. Block instead of silently dropping/repositioning.
            comments = document.get("comments", [])
            if not isinstance(comments, list) or len(comments) > 1024:
                raise KnxError("knx_export_source_unavailable")
            # Leading document comments precede every retained child. Their
            # position is unchanged even when only selected addresses follow.
            for position, comment in enumerate(comments):
                if (
                    not isinstance(comment, dict)
                    or comment.get("parents") != []
                    or comment.get("position") != position
                    or "address" in comment
                ):
                    raise KnxError("knx_export_source_unavailable")
            root = ET.Element(TAG + "GroupAddress-Export", _attributes(document.get("attributes")))
            for comment in comments:
                value = text(comment.get("text"), 4096)
                if "--" in value or value.endswith("-"):
                    raise KnxError("knx_export_source_unavailable")
                root.append(cast(ET.Element, ET.Comment(value)))
            marks = ",".join("?" for _ in requested)
            records = db.execute(
                "SELECT a.address,a.imported,s.source FROM addresses a "
                "JOIN ets_sources s ON s.target=a.target AND s.address=a.address "
                "WHERE a.target=? AND a.address IN (" + marks + ") ORDER BY a.address",
                (self.target, *requested),
            ).fetchall()
            if len(records) != len(requested):
                raise KnxError("knx_export_source_unavailable")
            sources = [
                (number, _decode(imported), _decode(raw)) for number, imported, raw in records
            ]
            styles = {source.get("address_format") for _, _, source in sources}
            if len(styles) != 1 or not styles <= {"two_level", "three_level"}:
                raise KnxError("knx_export_source_unavailable")
            style = next(iter(styles))
            required: set[str] = set()
            for _, _, source in sources:
                parents = source.get("parents")
                if not isinstance(parents, list) or len(parents) > (
                    2 if style == "three_level" else 1
                ):
                    raise KnxError("knx_export_source_unavailable")
                if any(
                    not isinstance(prefix, str)
                    or not re.fullmatch(r"(0|[1-9]|[12][0-9]|3[01])(?:/[0-7])?", prefix)
                    or prefix.count("/") != depth
                    for depth, prefix in enumerate(parents)
                ):
                    raise KnxError("knx_export_source_unavailable")
                if len(parents) == 2 and parents[1].split("/")[0] != parents[0]:
                    raise KnxError("knx_export_source_unavailable")
                required.update(parents)
            groups: dict[str, dict[str, str]] = {}
            if required:
                marks = ",".join("?" for _ in required)
                for prefix, raw in db.execute(
                    "SELECT prefix,source FROM import_groups WHERE target=? AND format=? "
                    "AND prefix IN (" + marks + ")",
                    (self.target, style, *required),
                ):
                    source = _decode(raw)
                    self._provenance(source, state)
                    groups[prefix] = _attributes(source.get("attributes"))
                if set(groups) != required:
                    raise KnxError("knx_export_source_unavailable")
            containers: dict[str, ET.Element] = {}
            for prefix in sorted(
                groups, key=lambda item: tuple(int(part) for part in item.split("/"))
            ):
                parent = containers[prefix.split("/")[0]] if "/" in prefix else root
                containers[prefix] = ET.SubElement(parent, TAG + "GroupRange", groups[prefix])
            changes = []
            for number, imported, source in sources:
                self._provenance(source, state)
                attrs = _attributes(source.get("attributes"))
                if address(attrs.get("Address"), style)[0] != number:
                    raise KnxError("knx_export_source_unavailable")
                if any(
                    attrs.get({"name": "Name", "description": "Description"}[key]) != value
                    for key, value in imported.items()
                    if key in {"name", "description"}
                ):
                    raise KnxError("knx_export_source_unavailable")
                after = dict(attrs)
                for key, value in requested[number].items():
                    after[{"name": "Name", "description": "Description"}[key]] = value
                parent = containers[source["parents"][-1]] if source["parents"] else root
                ET.SubElement(parent, TAG + "GroupAddress", after)
                changes.append(
                    {
                        "address_id": number,
                        "address": attrs["Address"],
                        "before": attrs,
                        "after": after,
                        "hierarchy": source["parents"],
                    }
                )
            ET.register_namespace("", NAMESPACE)
            body = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            outer = document.get("outer_comments", [])
            if not isinstance(outer, list):
                raise KnxError("knx_export_source_unavailable")
            before: list[bytes] = []
            after_comments: list[bytes] = []
            for comment in outer:
                if not isinstance(comment, dict) or comment.get("location") not in {
                    "before",
                    "after",
                }:
                    raise KnxError("knx_export_source_unavailable")
                value = text(comment.get("text"), 4096)
                if "--" in value or value.endswith("-"):
                    raise KnxError("knx_export_source_unavailable")
                (before if comment["location"] == "before" else after_comments).append(
                    ET.tostring(cast(ET.Element, ET.Comment(value)), encoding="utf-8")
                )
            declaration, content = body.split(b"\n", 1)
            body = b"\n".join([declaration, *before, content, *after_comments])
            if len(body) > MAX_FILE_BYTES:
                raise KnxError("knx_file_limit")
            parsed = parse_xml(body)
            if len(parsed.addresses) != len(requested) or len(parsed.groups) != len(required):
                raise KnxError("knx_export_source_unavailable")
        identifier = self.drafts.create(
            self.target, expected, body, {"project_binding": binding}, slot="xml_export"
        )
        return {
            "draft_id": identifier,
            "revision": expected,
            "project_binding": binding,
            "rows": changes,
            "groups": groups,
            "root_attributes": root.attrib,
            "document_comments": comments,
            "outer_comments": outer,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "experimental": True,
        }

    @staticmethod
    def _provenance(source: dict[str, Any], state: dict[str, Any]) -> None:
        if (
            not isinstance(state.get("imported_at"), int | float)
            or not isinstance(state.get("document_digest"), str)
            or len(state["document_digest"]) != 64
            or source.get("file_format") != "xml"
            or source.get("document_digest") != state.get("document_digest")
            or source.get("imported_at") != state.get("imported_at")
        ):
            raise KnxError("knx_export_source_unavailable")

    def download(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed_experimental") is not True:
            raise KnxError("knx_export_confirmation_required")
        with self.store.connection() as db:
            db.execute("BEGIN")
            expected = self.store.revision(db, self.target)
            if type(payload.get("revision")) is not int or payload.get("revision") != expected:
                raise KnxError("knx_revision_conflict")
            raw, options = self.drafts.load(payload.get("draft_id"), self.target, expected)
            if options.get("draft_slot") != "xml_export":
                raise KnxError("knx_draft_invalid")
            if payload.get("project_binding") != options.get("project_binding"):
                raise KnxError("knx_revision_conflict")
            return {
                "content": raw.decode("utf-8"),
                "filename": "knx-corrections-experimental.xml",
                "revision": expected,
                "experimental": True,
            }
