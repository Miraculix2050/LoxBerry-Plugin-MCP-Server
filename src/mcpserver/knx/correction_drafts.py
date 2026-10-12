"""Persistent revision-bound proposals sharing the existing bounded draft store."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .drafts import MAX_DRAFT_BYTES, MAX_DRAFTS, DraftStore
from .model import MAX_FILE_BYTES, KnxError, text

CORRECTION_TTL_SECONDS = 24 * 60 * 60
MAX_CORRECTION_CHANGES = 50
MAX_CORRECTION_OPERATIONS = 128
MAX_CORRECTION_OPTIONS_BYTES = MAX_FILE_BYTES


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{48}", value):
        raise KnxError("knx_draft_invalid")
    return value


def _revision(value: object) -> int:
    if type(value) is not int or value < 0:
        raise KnxError("knx_revision_conflict")
    return value


def _request(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise KnxError("knx_correction_invalid")
    return hashlib.sha256(value.encode()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _encode(options: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(options, ensure_ascii=True, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        raise KnxError("knx_draft_invalid") from None
    if len(encoded) > MAX_CORRECTION_OPTIONS_BYTES:
        raise KnxError("knx_draft_limit")
    return encoded


def _decode(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise KnxError("knx_draft_storage_failed") from None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("draft_slot") != "correction"
        or type(value.get("draft_revision")) is not int
        or value["draft_revision"] < 1
        or not isinstance(value.get("changes"), list)
        or not 1 <= len(value["changes"]) <= MAX_CORRECTION_CHANGES
    ):
        raise KnxError("knx_draft_storage_failed")
    return value


class CorrectionDraftStore(DraftStore):
    """Internal persistence; callers separately authorize the exact owner/target.

    The owner supplied to DraftStore is an installation-keyed principal digest,
    never an OAuth token or Admin cookie. No import, XML or catalog is changed.
    Domain services validate proposal fields before calling this repository.
    """

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        with super().connection() as db:
            present = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='correction_index'"
            ).fetchone()
            if present is None:
                # A missing index beside persistent correction data is corruption,
                # not a genuinely empty inventory. Legacy import-only stores migrate.
                if db.execute(
                    "SELECT 1 FROM drafts "
                    "WHERE json_extract(options,'$.draft_slot')='correction' LIMIT 1"
                ).fetchone():
                    raise KnxError("knx_draft_storage_failed")
                db.execute(
                    "CREATE TABLE correction_index (id TEXT PRIMARY KEY, owner TEXT NOT NULL, "
                    "target TEXT NOT NULL, catalog_revision INTEGER NOT NULL, "
                    "draft_revision INTEGER NOT NULL, created_at INTEGER NOT NULL, "
                    "expires_at INTEGER NOT NULL, manual_revision TEXT NOT NULL, "
                    "project_binding_digest TEXT, change_count INTEGER NOT NULL)"
                )
                db.execute("CREATE INDEX correction_owner_target ON correction_index(owner,target)")
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS correction_discard AFTER DELETE ON drafts "
                "BEGIN DELETE FROM correction_index WHERE id=OLD.id; END"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(correction_index)")}
            for column in ("request_key", "request_digest"):
                if column not in columns:
                    db.execute("ALTER TABLE correction_index ADD COLUMN " + column + " TEXT")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS correction_request "
                "ON correction_index(owner,target,request_key) WHERE request_key IS NOT NULL"
            )
            yield db

    def list_corrections(self, target: str) -> list[dict[str, Any]]:
        """Read compact own-draft metadata without hydrating proposal contents."""
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,catalog_revision,expires_at,draft_revision,created_at,"
                "manual_revision,project_binding_digest,change_count FROM correction_index "
                "WHERE owner=? AND target=? ORDER BY expires_at,id",
                (self.session, target),
            ).fetchall()
        return [
            {
                "draft_id": row[0],
                "catalog_revision": row[1],
                "expires_at": row[2],
                "draft_revision": row[3],
                "created_at": row[4],
                "manual_revision": row[5],
                "project_binding_digest": row[6],
                "change_count": row[7],
            }
            for row in rows
        ]

    def create_correction(
        self,
        target: str,
        catalog_revision: int,
        manual_revision: str,
        changes: list[dict[str, Any]],
        *,
        project_binding: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        text(target, 512, empty=False)
        _revision(catalog_revision)
        if not re.fullmatch(r"[0-9a-f]{64}", manual_revision):
            raise KnxError("knx_revision_conflict")
        if not 1 <= len(changes) <= MAX_CORRECTION_CHANGES:
            raise KnxError("knx_draft_limit")
        if project_binding is not None:
            text(project_binding, 4096, empty=False)
        request_key = _request(request_id)
        request_digest = _digest(
            [target, catalog_revision, manual_revision, changes, project_binding]
        )
        now = int(time.time())
        options = {
            "draft_slot": "correction",
            "schema_version": 1,
            "created_at": now,
            "draft_revision": 1,
            "manual_revision": manual_revision,
            "project_binding": project_binding,
            "changes": changes,
        }
        encoded = _encode(options)
        identifier = secrets.token_hex(24)
        expires = now + CORRECTION_TTL_SECONDS
        with self.connection() as db:
            previous = None
            if request_key is not None:
                previous = db.execute(
                    "SELECT id,request_digest FROM correction_index "
                    "WHERE owner=? AND target=? AND request_key=?",
                    (self.session, target, request_key),
                ).fetchone()
                if previous is not None:
                    if previous[1] != request_digest:
                        raise KnxError("knx_correction_request_conflict")
                    identifier = previous[0]
            if previous is not None:
                # The bounded index resolves an uncertain earlier preparation;
                # no second draft or expiry extension is produced.
                if db.execute("SELECT 1 FROM drafts WHERE id=?", (identifier,)).fetchone() is None:
                    raise KnxError("knx_draft_storage_failed")
            else:
                self._insert(
                    db,
                    identifier,
                    target,
                    catalog_revision,
                    manual_revision,
                    changes,
                    project_binding,
                    now,
                    expires,
                    encoded,
                    request_key,
                    request_digest,
                )
        return self.inspect_correction(identifier, target)

    def _insert(
        self,
        db: sqlite3.Connection,
        identifier: str,
        target: str,
        catalog_revision: int,
        manual_revision: str,
        changes: list[dict[str, Any]],
        project_binding: str | None,
        now: int,
        expires: int,
        encoded: str,
        request_key: str | None,
        request_digest: str,
    ) -> None:
        count, size = db.execute(
            "SELECT count(*),coalesce(sum(length(raw)+length(options)),0) FROM drafts"
        ).fetchone()
        if count >= MAX_DRAFTS or size + len(encoded) + 2 > MAX_DRAFT_BYTES:
            raise KnxError("knx_draft_limit")
        db.execute(
            "INSERT INTO drafts VALUES(?,?,?,?,?,?,?)",
            (identifier, self.session, target, catalog_revision, expires, b"{}", encoded),
        )
        db.execute(
            "INSERT INTO correction_index VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                self.session,
                target,
                catalog_revision,
                1,
                now,
                expires,
                manual_revision,
                hashlib.sha256(project_binding.encode()).hexdigest()
                if project_binding is not None
                else None,
                len(changes),
                request_key,
                request_digest,
            ),
        )

    def resolve_request(self, request_id: str, target: str) -> str:
        """Resolve an uncertain creation using only the caller's small index."""
        request_key = _request(request_id)
        with self.connection() as db:
            row = db.execute(
                "SELECT id FROM correction_index WHERE owner=? AND target=? AND request_key=?",
                (self.session, target, request_key),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            return str(row[0])

    def list_admin(self, target: str) -> list[dict[str, Any]]:
        """Compact target-wide discovery for the independently authenticated Admin adapter.

        This method must never be exposed by the delegated MCP adapter.
        Inspection selects one explicit draft; MCP owners remain isolated.
        """
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,draft_revision,expires_at,change_count FROM correction_index "
                "WHERE target=? ORDER BY expires_at,id",
                (target,),
            ).fetchall()
        return [
            dict(draft_id=row[0], draft_revision=row[1], expires_at=row[2], change_count=row[3])
            for row in rows
        ]

    def admin_reader(self, identifier: object, target: str) -> CorrectionDraftStore:
        """Select one existing owner's repository after independent Admin authentication."""
        identifier = _identifier(identifier)
        with self.connection() as db:
            row = db.execute(
                "SELECT owner FROM correction_index WHERE id=? AND target=?", (identifier, target)
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            if not isinstance(row[0], str) or not re.fullmatch(r"[0-9a-f]{64}", row[0]):
                raise KnxError("knx_draft_storage_failed")
        reader = CorrectionDraftStore(self.path, "0" * 64)
        # Already installation-keyed and hashed by DraftStore. Never return it
        # to the browser, or accept an owner value supplied by a client.
        reader.session = row[0]
        return reader

    def inspect_correction(self, identifier: object, target: str) -> dict[str, Any]:
        """A stale catalog revision does not hide an owner's proposal."""
        identifier = _identifier(identifier)
        with self.connection() as db:
            row = db.execute(
                "SELECT revision,expires,options FROM drafts "
                "WHERE id=? AND session=? AND target=? "
                "AND json_extract(options,'$.draft_slot')='correction'",
                (identifier, self.session, target),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            options = _decode(row[2])
            self._check_index(db, identifier, options)
            return {
                "draft_id": identifier,
                "target": target,
                "catalog_revision": row[0],
                "expires_at": row[1],
                **{
                    key: value
                    for key, value in options.items()
                    if key not in {"draft_slot", "operations"}
                },
            }

    def update_correction(
        self,
        identifier: object,
        target: str,
        expected: object,
        changes: list[dict[str, Any]],
        *,
        request_id: str | None = None,
        operation_payload: object = None,
    ) -> int:
        """Optimistic edits preserve the absolute expiry and source revisions."""
        identifier = _identifier(identifier)
        _revision(expected)
        if not 1 <= len(changes) <= MAX_CORRECTION_CHANGES:
            raise KnxError("knx_draft_limit")
        request_key = _request(request_id)
        request_digest = _digest(
            [
                identifier,
                target,
                expected,
                changes if operation_payload is None else operation_payload,
            ]
        )
        with self.connection() as db:
            row = db.execute(
                "SELECT options FROM drafts WHERE id=? AND session=? AND target=? "
                "AND json_extract(options,'$.draft_slot')='correction'",
                (identifier, self.session, target),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            options = _decode(row[0])
            self._check_index(db, identifier, options)
            operations = options.get("operations", {})
            if not isinstance(operations, dict):
                raise KnxError("knx_draft_storage_failed")
            if request_key is not None and request_key in operations:
                previous = operations[request_key]
                if not isinstance(previous, dict) or previous.get("digest") != request_digest:
                    raise KnxError("knx_correction_request_conflict")
                return _revision(previous.get("revision"))
            if options.get("draft_revision") != expected:
                raise KnxError("knx_revision_conflict")
            if request_key is not None:
                if len(operations) >= MAX_CORRECTION_OPERATIONS:
                    raise KnxError("knx_draft_limit")
                operations[request_key] = {
                    "digest": request_digest,
                    "revision": _revision(expected) + 1,
                }
                options["operations"] = operations
            options.update(changes=changes, draft_revision=_revision(expected) + 1)
            encoded = _encode(options)
            size = db.execute(
                "SELECT coalesce(sum(length(raw)+length(options)),0) FROM drafts WHERE id<>?",
                (identifier,),
            ).fetchone()[0]
            if size + len(encoded) + 2 > MAX_DRAFT_BYTES:
                raise KnxError("knx_draft_limit")
            db.execute("UPDATE drafts SET options=? WHERE id=?", (encoded, identifier))
            db.execute(
                "UPDATE correction_index SET draft_revision=?,change_count=? WHERE id=?",
                (_revision(expected) + 1, len(changes), identifier),
            )
            return _revision(expected) + 1

    def reconcile_update(
        self,
        identifier: object,
        target: str,
        expected: object,
        request_id: str,
        operation_payload: object,
    ) -> int | None:
        """Resolve an exact earlier edit before validating its now-old revisions.

        Callers still check live owner/target authorization. This is a receipt
        lookup, not an invitation to retry an uncertain request automatically.
        """
        identifier = _identifier(identifier)
        _revision(expected)
        key = _request(request_id)
        if key is None:
            raise KnxError("knx_correction_invalid")
        digest = _digest([identifier, target, expected, operation_payload])
        with self.connection() as db:
            row = db.execute(
                "SELECT options FROM drafts WHERE id=? AND session=? AND target=? "
                "AND json_extract(options,'$.draft_slot')='correction'",
                (identifier, self.session, target),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            options = _decode(row[0])
            self._check_index(db, identifier, options)
            operations = options.get("operations", {})
            if not isinstance(operations, dict):
                raise KnxError("knx_draft_storage_failed")
            previous = operations.get(key)
            if previous is None:
                return None
            if not isinstance(previous, dict) or previous.get("digest") != digest:
                raise KnxError("knx_correction_request_conflict")
            return _revision(previous.get("revision"))

    def discard_correction(self, identifier: object, target: str, expected: object) -> None:
        identifier = _identifier(identifier)
        _revision(expected)
        with self.connection() as db:
            row = db.execute(
                "SELECT options FROM drafts WHERE id=? AND session=? AND target=? "
                "AND json_extract(options,'$.draft_slot')='correction'",
                (identifier, self.session, target),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_unavailable")
            options = _decode(row[0])
            self._check_index(db, identifier, options)
            if options["draft_revision"] != expected:
                raise KnxError("knx_revision_conflict")
            db.execute("DELETE FROM drafts WHERE id=?", (identifier,))

    def _check_index(
        self, db: sqlite3.Connection, identifier: str, options: dict[str, Any]
    ) -> None:
        row = db.execute(
            "SELECT draft_revision,change_count FROM correction_index WHERE id=? AND owner=?",
            (identifier, self.session),
        ).fetchone()
        if row != (options["draft_revision"], len(options["changes"])):
            raise KnxError("knx_draft_storage_failed")
