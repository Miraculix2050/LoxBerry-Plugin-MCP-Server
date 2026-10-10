"""Transactional ETS catalog persistence, outside every MCP read path."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Generator
from typing import Any

from .import_model import MAX_GROUPS, ImportDocument, ImportSelection
from .model import MAX_ADDRESSES, KnxError, text
from .store import KnxStore


class ImportRepository:
    def __init__(self, store: KnxStore) -> None:
        self.store = store

    def snapshot(self, target: str) -> dict[str, Any]:
        with self.store.connection() as db:
            db.execute("BEGIN")
            return {
                "revision": self.store.revision(db, target),
                "addresses": {
                    number: None
                    for (number,) in db.execute(
                        "SELECT address FROM addresses WHERE target=?", (target,)
                    )
                },
                "groups": {
                    (fmt, prefix): {"fields": json.loads(fields), "selected": bool(selected)}
                    for fmt, prefix, fields, selected in db.execute(
                        "SELECT format,prefix,fields,selected FROM import_groups WHERE target=?",
                        (target,),
                    )
                },
            }

    def address_rows(
        self, target: str, numbers: list[int], expected: int
    ) -> Generator[tuple[int, dict[str, Any]]]:
        """Stream relevant rows without retaining the complete metadata catalog."""
        with self.store.connection() as db:
            db.execute("BEGIN")
            self.store.check(db, target, expected)
            db.execute("CREATE TEMP TABLE requested_addresses(address INTEGER PRIMARY KEY)")
            db.executemany(
                "INSERT INTO requested_addresses VALUES(?)", [(number,) for number in numbers]
            )
            for number, fmt, original, imported, overrides in db.execute(
                "SELECT a.address,a.format,a.original,a.imported,a.overrides FROM addresses AS a "
                "JOIN requested_addresses AS r ON r.address=a.address "
                "WHERE a.target=? ORDER BY a.address",
                (target,),
            ):
                yield (
                    number,
                    {
                        "address_format": fmt,
                        "address": original,
                        "imported": json.loads(imported),
                        "overrides": json.loads(overrides),
                    },
                )

    def selected_labels(self, target: str) -> list[dict[str, str]]:
        with self.store.connection() as db:
            return [
                {"address_format": fmt, "prefix": prefix, "label": json.loads(fields)["name"]}
                for fmt, prefix, fields in db.execute(
                    "SELECT format,prefix,fields FROM import_groups WHERE target=? AND selected=1 "
                    "ORDER BY format,prefix",
                    (target,),
                )
            ]

    def apply(
        self,
        target: str,
        expected: int,
        document: ImportDocument,
        selection: ImportSelection,
        selected_groups: set[tuple[str, str]],
        information: dict[str, Any],
        *,
        mode: str = "merge",
        orphan_name_policy: str | None = None,
    ) -> int:
        """Update sources atomically; replacement never removes manual records."""
        if mode not in {"merge", "replace"} or (
            mode == "replace" and information.get("complete_export") is not True
        ):
            raise KnxError("knx_import_mode_invalid")
        if orphan_name_policy not in {None, "keep_unknown", "retain_import_name"}:
            raise KnxError("knx_orphan_name_policy_invalid")
        if selection.conflicts:
            raise KnxError("knx_import_conflicts")
        if len(selected_groups) > 128:
            raise KnxError("knx_label_limit")
        for group in selection.groups:
            if (group.address_format, group.prefix) in selected_groups:
                text(group.fields["name"], 80, empty=False)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.store.check(db, target, expected)
            db.execute("INSERT OR IGNORE INTO targets(target) VALUES(?)", (target,))
            if mode == "replace":
                db.execute("CREATE TEMP TABLE incoming_addresses(address INTEGER PRIMARY KEY)")
                db.executemany(
                    "INSERT INTO incoming_addresses VALUES(?)",
                    ((row.number,) for row in selection.addresses),
                )
                absent = (
                    "target=? AND imported!='{}' AND address NOT IN "
                    "(SELECT address FROM incoming_addresses)"
                )
                for number, imported, overrides in db.execute(
                    "SELECT address,imported,overrides FROM addresses WHERE " + absent, (target,)
                ):
                    fields = json.loads(overrides)
                    if fields and "name" not in fields:
                        if orphan_name_policy is None:
                            raise KnxError("knx_orphan_name_policy_required")
                        if orphan_name_policy == "retain_import_name":
                            fields["name"] = json.loads(imported)["name"]
                            db.execute(
                                "UPDATE addresses SET overrides=? WHERE target=? AND address=?",
                                (json.dumps(fields), target, number),
                            )
                db.execute(
                    "DELETE FROM ets_sources WHERE target=? AND address NOT IN "
                    "(SELECT address FROM incoming_addresses)",
                    (target,),
                )
                db.execute(
                    "DELETE FROM addresses WHERE " + absent + " AND overrides='{}'", (target,)
                )
                db.execute("UPDATE addresses SET imported='{}' WHERE " + absent, (target,))
                # The incoming group list is the complete replacement of import metadata.
                db.execute("DELETE FROM import_groups WHERE target=?", (target,))
            db.executemany(
                "INSERT INTO addresses(target,address,format,original,imported,overrides) "
                "VALUES(?,?,?,?,?,'{}') ON CONFLICT(target,address) DO UPDATE SET "
                "imported=excluded.imported",
                [
                    (
                        target,
                        row.number,
                        row.address_format,
                        row.original,
                        json.dumps(row.fields, ensure_ascii=False),
                    )
                    for row in selection.addresses
                ],
            )
            stamp = time.time()
            root_digest = hashlib.sha256(
                json.dumps(document.source, sort_keys=True).encode()
            ).hexdigest()
            db.executemany(
                "INSERT INTO ets_sources VALUES(?,?,?) ON CONFLICT(target,address) "
                "DO UPDATE SET source=excluded.source",
                [
                    (
                        target,
                        row.number,
                        json.dumps(
                            {
                                **row.source,
                                "document_digest": root_digest,
                                "address_format": row.address_format,
                                "file_format": document.file_format,
                                "encoding": document.encoding,
                                "imported_at": stamp,
                                **information,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    for row in selection.addresses
                ],
            )
            db.executemany(
                "INSERT INTO import_groups VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(target,format,prefix) DO UPDATE SET fields=excluded.fields, "
                "source=excluded.source,selected=excluded.selected",
                [
                    (
                        target,
                        row.address_format,
                        row.prefix,
                        json.dumps(row.fields, ensure_ascii=False),
                        json.dumps(row.source, ensure_ascii=False),
                        int((row.address_format, row.prefix) in selected_groups),
                    )
                    for row in selection.groups
                ],
            )
            db.execute("UPDATE import_groups SET selected=0 WHERE target=?", (target,))
            db.executemany(
                "UPDATE import_groups SET selected=1 WHERE target=? AND format=? AND prefix=?",
                [(target, fmt, prefix) for fmt, prefix in selected_groups],
            )
            count = db.execute(
                "SELECT count(*) FROM addresses WHERE target=?", (target,)
            ).fetchone()[0]
            groups = db.execute(
                "SELECT count(*) FROM import_groups WHERE target=?", (target,)
            ).fetchone()[0]
            selected = db.execute(
                "SELECT count(*) FROM import_groups WHERE target=? AND selected=1", (target,)
            ).fetchone()[0]
            if selected != len(selected_groups):
                raise KnxError("knx_label_selection_invalid")
            if count > MAX_ADDRESSES or groups > MAX_GROUPS or selected > 128:
                raise KnxError("knx_import_limit")
            db.execute(
                "INSERT INTO import_state VALUES(?,?) ON CONFLICT(target) "
                "DO UPDATE SET information=excluded.information",
                (
                    target,
                    json.dumps(
                        {
                            **information,
                            "imported_at": stamp,
                            "document": document.source,
                            "document_digest": root_digest,
                        }
                    ),
                ),
            )
            db.execute("UPDATE targets SET revision=revision+1 WHERE target=?", (target,))
            revision = self.store.revision(db, target)
            db.commit()
            return revision
