"""Read-only comparison of explicit ETS inputs, separate from import application."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Iterable, Iterator
from contextlib import closing
from typing import Any

from .catalog_service import CatalogService
from .drafts import DraftStore
from .import_model import MAX_GROUPS, ImportSelection
from .import_service import select_candidates
from .model import FIELDS, MAX_ADDRESSES, KnxError, metadata
from .read_model import datapoint
from .store import KnxStore

PAGE_SIZE = 50
MAX_COMPARISON_ROWS = MAX_ADDRESSES + 2 * MAX_GROUPS + 128
AddressRow = tuple[int, str, str, dict[str, Any], dict[str, Any]]


def _stored(raw: str) -> dict[str, Any]:
    try:
        return metadata(json.loads(raw))
    except ValueError:
        raise KnxError("knx_storage_failed") from None


def _canonical(fields: dict[str, Any], key: str) -> Any:
    if key not in fields:
        return ("unknown",)
    value = fields[key]
    if key == "dpts":
        return ("specified", frozenset(datapoint(item)["normalized"] or item for item in value))
    return ("specified", value)


def _differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return [key for key in sorted(FIELDS) if _canonical(left, key) != _canonical(right, key)]


def _file_rows(selection: ImportSelection) -> Iterator[AddressRow]:
    for row in selection.addresses:
        yield row.number, row.original, row.address_format, row.fields, {}


def _paired(
    left: Iterable[AddressRow], right: Iterable[AddressRow]
) -> Generator[tuple[AddressRow | None, AddressRow | None]]:
    """Merge ordered keys without retaining the stored catalog's source values."""
    first, second = iter(left), iter(right)
    a, b = next(first, None), next(second, None)
    while a is not None or b is not None:
        if b is None or (a is not None and a[0] < b[0]):
            yield a, None
            a = next(first, None)
        elif a is None or b[0] < a[0]:
            yield None, b
            b = next(second, None)
        else:
            yield a, b
            a, b = next(first, None), next(second, None)


class FileComparison:
    def __init__(
        self,
        store: KnxStore,
        drafts: DraftStore,
        target: str,
        manual_labels: list[dict[str, str]],
    ) -> None:
        self.store, self.drafts, self.target = store, drafts, target
        self.manual_labels = manual_labels

    def manual_revision(self) -> str:
        return hashlib.sha256(json.dumps(self.manual_labels, sort_keys=True).encode()).hexdigest()

    def load(self, raw: bytes, side: object, options: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(side, str) or side not in {"left", "right"}:
            raise KnxError("knx_comparison_invalid")
        if type(options.get("complete_export")) is not bool:
            raise KnxError("knx_scope_invalid")
        if options.get("address_format") not in (None, "two_level", "three_level"):
            raise KnxError("knx_format_invalid")
        document = CatalogService.parse(raw, options)
        selection = select_candidates(document)
        # Contradictory duplicate records are not an ordered snapshot. Never
        # choose a candidate implicitly; use a corrected input for comparison.
        if selection.conflicts:
            raise KnxError("knx_comparison_conflicts")
        with self.store.connection() as db:
            revision = self.store.revision(db, self.target)
        identifier = self.drafts.create(
            self.target,
            revision,
            raw,
            {**options, "comparison_manual_revision": self.manual_revision()},
            slot="compare_" + side,
        )
        return {
            "draft_id": identifier,
            "revision": revision,
            "taxonomy_revision": self.manual_revision(),
            "side": side,
            "file_format": document.file_format,
            "encoding": document.encoding,
            "address_format": document.address_format,
            "addresses": len(selection.addresses),
            "groups": len(selection.groups),
            "complete_export": options["complete_export"],
            "merged_duplicates": selection.merged_duplicates,
        }

    def _input(
        self, identifier: object, side: str, revision: int
    ) -> tuple[ImportSelection, dict[str, Any]]:
        raw, options = self.drafts.load(identifier, self.target, revision)
        if options.get("draft_slot") != "compare_" + side:
            raise KnxError("knx_comparison_invalid")
        if options.get("comparison_manual_revision") != self.manual_revision():
            raise KnxError("knx_revision_conflict")
        document = CatalogService.parse(raw, options)
        selection = select_candidates(document)
        if selection.conflicts:
            raise KnxError("knx_comparison_conflicts")
        return selection, {
            "kind": "file",
            "file_format": document.file_format,
            "encoding": document.encoding,
            "address_format": document.address_format,
            "completeness": "complete" if options["complete_export"] else "partial",
            "addresses": len(selection.addresses),
            "groups": len(selection.groups),
            "merged_duplicates": selection.merged_duplicates,
        }

    def page(self, payload: dict[str, Any]) -> dict[str, Any]:
        revision, offset = payload.get("revision"), payload.get("offset", 0)
        if (
            type(revision) is not int
            or type(offset) is not int
            or not 0 <= offset <= MAX_COMPARISON_ROWS
        ):
            raise KnxError("knx_page_invalid")
        if payload.get("taxonomy_revision") != self.manual_revision():
            raise KnxError("knx_revision_conflict")
        right, right_info = self._input(payload.get("right_id"), "right", revision)
        stored = payload.get("left_id") == "current"
        left: ImportSelection | None = None
        if not stored:
            left, left_info = self._input(payload.get("left_id"), "left", revision)
        else:
            left_info = {"kind": "current_import_catalog", "completeness": "unknown"}
        counts = {
            kind: {key: 0 for key in ("added", "removed", "changed", "manual", "unchanged")}
            for kind in ("address", "group")
        }
        rows: list[dict[str, Any]] = []
        total = 0

        def observe(
            kind: str,
            identity: str,
            before: dict[str, Any],
            after: dict[str, Any],
            manual: dict[str, Any],
            display: dict[str, Any],
        ) -> None:
            nonlocal total
            fields = _differences(before, after)
            change = (
                "added"
                if not before and after
                else "removed"
                if before and not after
                else "changed"
                if fields
                else "manual"
                if manual
                else "unchanged"
            )
            counts[kind][change] += 1
            if change == "unchanged":
                return
            if offset <= total < offset + PAGE_SIZE:
                rows.append(
                    {
                        "kind": kind,
                        "identity": identity,
                        "change": change,
                        "before": before,
                        "after": after,
                        "changed_fields": fields,
                        "manual": manual,
                        **display,
                    }
                )
            total += 1

        with self.store.connection() as db:
            db.execute("BEGIN")
            self.store.check(db, self.target, revision)
            if stored:
                info = db.execute(
                    "SELECT information FROM import_state WHERE target=?", (self.target,)
                ).fetchone()
                if info is None:
                    raise KnxError("knx_comparison_no_import")
                try:
                    information = json.loads(info[0])
                except ValueError:
                    raise KnxError("knx_storage_failed") from None
                if not isinstance(information, dict):
                    raise KnxError("knx_storage_failed")
                left_info["latest_complete_export"] = information.get("complete_export")
                left_info["latest_mode"] = information.get("mode")

                def catalog_rows() -> Iterator[AddressRow]:
                    for number, fmt, original, imported, overrides in db.execute(
                        "SELECT address,format,original,imported,overrides FROM addresses "
                        "WHERE target=? ORDER BY address",
                        (self.target,),
                    ):
                        yield number, original, fmt, _stored(imported), _stored(overrides)

                source_rows = catalog_rows()
                left_groups = {
                    (fmt, prefix): _stored(fields)
                    for fmt, prefix, fields in db.execute(
                        "SELECT format,prefix,fields FROM import_groups WHERE target=?",
                        (self.target,),
                    )
                }
                manual_groups = {
                    (row["address_format"], row["prefix"]): {"name": row["label"]}
                    for row in self.manual_labels
                }
            else:
                assert left is not None
                source_rows = _file_rows(left)
                left_groups = {(row.address_format, row.prefix): row.fields for row in left.groups}
                manual_groups = {}
            with closing(_paired(source_rows, _file_rows(right))) as pairs:
                for a, b in pairs:
                    number = a[0] if a is not None else b[0] if b is not None else -1
                    observe(
                        "address",
                        str(number),
                        a[3] if a else {},
                        b[3] if b else {},
                        a[4] if a else {},
                        {
                            "address_id": number,
                            "before_address": a[1] if a else None,
                            "after_address": b[1] if b else None,
                            "before_format": a[2] if a else None,
                            "after_format": b[2] if b else None,
                        },
                    )
            right_groups = {(row.address_format, row.prefix): row.fields for row in right.groups}
            for fmt, prefix in sorted(
                left_groups.keys() | right_groups.keys() | manual_groups.keys()
            ):
                identity = (fmt, prefix)
                observe(
                    "group",
                    f"{fmt}:{prefix}",
                    left_groups.get(identity, {}),
                    right_groups.get(identity, {}),
                    manual_groups.get(identity, {}),
                    {"address_format": fmt, "prefix": prefix},
                )
        return {
            "revision": revision,
            "taxonomy_revision": self.manual_revision(),
            "left": left_info,
            "right": right_info,
            "counts": counts,
            "offset": offset,
            "total": total,
            "rows": rows,
            "has_more": offset + len(rows) < total,
            "manual_scope": "current_catalog_only" if stored else "not_part_of_files",
            "absence_scope": "selected_inputs_only",
            "catalog_changed": False,
        }
