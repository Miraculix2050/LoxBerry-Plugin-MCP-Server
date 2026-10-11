"""Revisioned, target-bound indexed KNX metadata persistence."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .model import MAX_ADDRESSES, KnxError, address, metadata
from .read_model import details, query_filters, query_sql, sql_deviates


def _search_document(number: int, original: str, imported: str, overrides: str) -> str:
    """Derived Unicode search fields; separators cannot match validated queries."""
    values = [
        original,
        f"{number >> 11}/{number & 2047}",
        f"{number >> 11}/{(number >> 8) & 7}/{number & 255}",
    ]
    for raw in (imported, overrides):
        fields = json.loads(raw)
        values.extend(fields.get(key, "") for key in ("name", "description"))
    return "\x00".join(values).casefold()


class KnxStore:
    def __init__(self, path: Path) -> None:
        if not path.is_absolute() or path.suffix != ".sqlite3":
            raise KnxError("knx_storage_invalid")
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise KnxError("knx_storage_invalid")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.create_function(
            "knx_casefold",
            1,
            lambda value: value.casefold() if isinstance(value, str) else "",
            deterministic=True,
        )
        connection.create_function("knx_deviates", 2, sql_deviates, deterministic=True)
        connection.create_function("knx_search_document", 4, _search_document, deterministic=True)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2, 3}:
                raise KnxError("knx_storage_version")
            if version == 0:
                connection.executescript(
                    "CREATE TABLE IF NOT EXISTS targets (target TEXT PRIMARY KEY, revision INTEGER "
                    "NOT NULL DEFAULT 0);"
                    "CREATE TABLE IF NOT EXISTS addresses (target TEXT NOT NULL, address INTEGER "
                    "NOT NULL, format TEXT NOT NULL, original TEXT NOT NULL, "
                    "imported TEXT NOT NULL "
                    "DEFAULT '{}', overrides TEXT NOT NULL, PRIMARY KEY(target,address), "
                    "FOREIGN KEY(target) REFERENCES targets(target)); PRAGMA user_version=1;"
                )
            if version < 2:
                connection.executescript(
                    "BEGIN IMMEDIATE;"
                    "CREATE TABLE IF NOT EXISTS ets_sources (target TEXT NOT NULL, address INTEGER "
                    "NOT NULL, source TEXT NOT NULL, PRIMARY KEY(target,address), "
                    "FOREIGN KEY(target,address) REFERENCES addresses(target,address) "
                    "ON DELETE CASCADE);"
                    "CREATE TABLE IF NOT EXISTS import_groups (target TEXT NOT NULL, "
                    "format TEXT NOT NULL, prefix TEXT NOT NULL, fields TEXT NOT NULL, "
                    "source TEXT NOT NULL, selected INTEGER "
                    "NOT NULL DEFAULT 0, PRIMARY KEY(target,format,prefix), "
                    "FOREIGN KEY(target) REFERENCES targets(target));"
                    "CREATE TABLE IF NOT EXISTS import_state (target TEXT PRIMARY KEY, "
                    "information TEXT "
                    "NOT NULL, FOREIGN KEY(target) REFERENCES targets(target));"
                    "PRAGMA user_version=2; COMMIT;"
                )
            if version < 3:
                connection.executescript(
                    "BEGIN IMMEDIATE;"
                    "ALTER TABLE addresses ADD COLUMN search_document TEXT NOT NULL DEFAULT '';"
                    "UPDATE addresses SET search_document="
                    "knx_search_document(address,original,imported,overrides);"
                    "CREATE TRIGGER addresses_search_insert AFTER INSERT ON addresses BEGIN "
                    "UPDATE addresses SET search_document=knx_search_document("
                    "NEW.address,NEW.original,NEW.imported,NEW.overrides) "
                    "WHERE target=NEW.target AND address=NEW.address; END;"
                    "CREATE TRIGGER addresses_search_update "
                    "AFTER UPDATE OF address,original,imported,overrides ON addresses BEGIN "
                    "UPDATE addresses SET search_document=knx_search_document("
                    "NEW.address,NEW.original,NEW.imported,NEW.overrides) "
                    "WHERE target=NEW.target AND address=NEW.address; END;"
                    "CREATE INDEX addresses_search_cover "
                    "ON addresses(target,search_document,address);"
                    "PRAGMA user_version=3; COMMIT;"
                )
            else:
                # Preserve databases from earlier schema-v3 test iterations.
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS addresses_search_cover "
                    "ON addresses(target,search_document,address)"
                )
            # Address-set comparisons read keys without fetching catalog JSON.
            # SQLite maintains membership when imports or manual records change.
            connection.execute(
                "CREATE INDEX IF NOT EXISTS addresses_imported "
                "ON addresses(target,address) WHERE imported!='{}'"
            )
            yield connection
        except sqlite3.Error:
            connection.rollback()
            raise KnxError("knx_storage_failed") from None
        finally:
            connection.close()

    @staticmethod
    def revision(db: sqlite3.Connection, target: str) -> int:
        row = db.execute("SELECT revision FROM targets WHERE target=?", (target,)).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def check(db: sqlite3.Connection, target: str, expected: object) -> None:
        if type(expected) is not int or expected != KnxStore.revision(db, target):
            raise KnxError("knx_revision_conflict")

    @staticmethod
    def project(row: tuple[Any, ...]) -> dict[str, Any]:
        number, fmt, original, raw, manual = row[:5]
        imported, overrides = json.loads(raw), json.loads(manual)
        source = json.loads(row[5]) if len(row) > 5 and row[5] else {}
        return {
            "address_id": number,
            "address_format": fmt,
            "address": original,
            "imported": imported,
            "overrides": overrides,
            "effective": {**imported, **overrides},
            **details(imported, overrides),
            "import_info": {
                key: source[key]
                for key in ("file_format", "encoding", "imported_at", "digest", "address_format")
                if key in source
            }
            | (
                {"address": source["attributes"]["Address"]}
                if "Address" in source.get("attributes", {})
                else {}
            ),
        }

    def page(
        self,
        target: str,
        offset: int = 0,
        limit: int = 50,
        *,
        filters: object = None,
        expected: object = None,
    ) -> dict[str, Any]:
        if type(offset) is not int or not 0 <= offset <= MAX_ADDRESSES:
            raise KnxError("knx_page_invalid")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise KnxError("knx_page_invalid")
        selection = query_filters(filters)
        where, arguments = query_sql(selection)
        if offset and filters is not None and expected is None:
            raise KnxError("knx_revision_conflict")
        with self.connection() as db:
            db.execute("BEGIN")
            revision = self.revision(db, target)
            if expected is not None:
                self.check(db, target, expected)
            total = db.execute(
                "SELECT count(*) FROM addresses AS a WHERE a.target=?" + where,
                [target, *arguments],
            ).fetchone()[0]
            rows = db.execute(
                "SELECT a.address,a.format,a.original,a.imported,a.overrides,s.source "
                "FROM addresses AS a LEFT JOIN ets_sources AS s "
                "ON s.target=a.target AND s.address=a.address "
                "WHERE a.target=?" + where + " ORDER BY a.address LIMIT ? OFFSET ?",
                [target, *arguments, limit, offset],
            ).fetchall()
            return {
                "revision": revision,
                "total": total,
                "offset": offset,
                "filters": selection,
                "items": [self.project(row) for row in rows],
            }

    def put(self, target: str, expected: object, value: object) -> int:
        if not isinstance(value, dict) or set(value) != {"address", "address_format", "fields"}:
            raise KnxError("knx_record_invalid")
        number, original = address(value["address"], value["address_format"])
        fields = metadata(value["fields"])
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check(db, target, expected)
            db.execute("INSERT OR IGNORE INTO targets(target) VALUES(?)", (target,))
            exists = db.execute(
                "SELECT imported FROM addresses WHERE target=? AND address=?", (target, number)
            ).fetchone()
            metadata({**(json.loads(exists[0]) if exists else {}), **fields}, require_name=True)
            count = db.execute(
                "SELECT count(*) FROM addresses WHERE target=?", (target,)
            ).fetchone()[0]
            if not exists and count >= MAX_ADDRESSES:
                raise KnxError("knx_address_limit")
            db.execute(
                "INSERT INTO addresses(target,address,format,original,overrides) VALUES(?,?,?,?,?) "
                "ON CONFLICT(target,address) DO UPDATE SET format=excluded.format, "
                "original=excluded.original, overrides=excluded.overrides",
                (target, number, value["address_format"], original, json.dumps(fields)),
            )
            db.execute("UPDATE targets SET revision=revision+1 WHERE target=?", (target,))
            revision = self.revision(db, target)
            db.commit()
            return revision

    def delete(self, target: str, expected: object, number: object) -> int:
        if type(number) is not int or not 0 <= number < MAX_ADDRESSES:
            raise KnxError("knx_address_invalid")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check(db, target, expected)
            db.execute("DELETE FROM addresses WHERE target=? AND address=?", (target, number))
            db.execute("UPDATE targets SET revision=revision+1 WHERE target=?", (target,))
            revision = self.revision(db, target)
            db.commit()
            return revision

    def export(
        self, target: str, offset: int = 0, *, filters: object = None, expected: object = None
    ) -> dict[str, Any]:
        page = self.page(target, offset, filters=filters, expected=expected)
        return {
            "schema_version": 1,
            "records": [
                {
                    k: row[k]
                    for k in ("address_id", "address_format", "address", "imported", "overrides")
                }
                for row in page["items"]
            ],
        }

    @staticmethod
    def exchange_records(document: object, target: str) -> list[tuple[Any, ...]]:
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "records"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or not isinstance(document["records"], list)
            or len(document["records"]) > MAX_ADDRESSES
        ):
            raise KnxError("knx_exchange_invalid")
        records = []
        seen: set[int] = set()
        for record in document["records"]:
            if not isinstance(record, dict) or set(record) != {
                "address_id",
                "address_format",
                "address",
                "imported",
                "overrides",
            }:
                raise KnxError("knx_exchange_invalid")
            number, original = address(record["address"], record["address_format"])
            if (
                type(record["address_id"]) is not int
                or number in seen
                or number != record["address_id"]
            ):
                raise KnxError("knx_exchange_duplicate")
            seen.add(number)
            imported, overrides = metadata(record["imported"]), metadata(record["overrides"])
            effective = {**imported, **overrides}
            # A complete replacement may preserve an override without inventing a name.
            # Such existing source states must remain exchangeable; new form entries still
            # require a name in put().
            if imported or not overrides or "name" in effective:
                metadata(effective, require_name=True)
            records.append(
                (
                    target,
                    number,
                    record["address_format"],
                    original,
                    json.dumps(imported),
                    json.dumps(overrides),
                )
            )
        return records

    def preview(self, target: str, document: object) -> dict[str, Any]:
        records = self.exchange_records(document, target)
        additions = 0
        update_count = 0
        updates: list[dict[str, Any]] = []
        with self.connection() as db:
            db.execute("BEGIN")
            revision = self.revision(db, target)
            for _, number, fmt, original, imported, overrides in records:
                existing = db.execute(
                    "SELECT format,original,imported,overrides FROM addresses "
                    "WHERE target=? AND address=?",
                    (target, number),
                ).fetchone()
                if existing is None:
                    additions += 1
                else:
                    old = {
                        "address_format": existing[0],
                        "address": existing[1],
                        "imported": json.loads(existing[2]),
                        "overrides": json.loads(existing[3]),
                    }
                    new = {
                        "address_format": fmt,
                        "address": original,
                        "imported": json.loads(imported),
                        "overrides": json.loads(overrides),
                    }
                    changed = sorted(key for key in old if old[key] != new[key])
                    if changed:
                        update_count += 1
                        if len(updates) < 50:
                            updates.append(
                                {"address": original, "fields": changed, "old": old, "new": new}
                            )
            return {
                "revision": revision,
                "additions": additions,
                "updates": update_count,
                "changes": updates,
                "changes_omitted": max(0, update_count - 50),
            }

    def restore(self, target: str, expected: object, document: object) -> int:
        records = self.exchange_records(document, target)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.check(db, target, expected)
            db.execute("INSERT OR IGNORE INTO targets(target) VALUES(?)", (target,))
            db.executemany(
                "INSERT INTO addresses(target,address,format,original,imported,overrides) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(target,address) DO UPDATE SET "
                "format=excluded.format, original=excluded.original, imported=excluded.imported, "
                "overrides=excluded.overrides",
                records,
            )
            # JSON exchange cannot establish reconstruction evidence for an ETS XML export.
            db.executemany(
                "DELETE FROM ets_sources WHERE target=? AND address=?",
                [(target, row[1]) for row in records],
            )
            count = db.execute(
                "SELECT count(*) FROM addresses WHERE target=?", (target,)
            ).fetchone()[0]
            if count > MAX_ADDRESSES:
                raise KnxError("knx_address_limit")
            db.execute("UPDATE targets SET revision=revision+1 WHERE target=?", (target,))
            revision = self.revision(db, target)
            db.commit()
            return revision
