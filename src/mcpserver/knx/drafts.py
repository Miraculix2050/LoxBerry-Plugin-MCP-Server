"""Short-lived bounded admin-session drafts, separate from catalog revisions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .model import MAX_FILE_BYTES, KnxError

TTL_SECONDS = 600
MAX_DRAFT_BYTES = 32 * 1024 * 1024
MAX_DRAFTS = 8


class DraftStore:
    def __init__(self, path: Path, session: str) -> None:
        if not path.is_absolute() or path.suffix != ".sqlite3":
            raise KnxError("knx_storage_invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", session):
            raise KnxError("knx_session_missing")
        self.path = path
        self.session = hashlib.sha256(session.encode()).hexdigest()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise KnxError("knx_storage_invalid")
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA max_page_count=10240")
            db.execute(
                "CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, session TEXT NOT NULL, "
                "target TEXT NOT NULL, revision INTEGER NOT NULL, expires REAL NOT NULL, "
                "raw BLOB NOT NULL, options TEXT NOT NULL)"
            )
            db.execute("DELETE FROM drafts WHERE expires<=?", (time.time(),))
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.Error:
            db.rollback()
            raise KnxError("knx_draft_storage_failed") from None
        finally:
            db.close()

    def create(
        self,
        target: str,
        revision: int,
        raw: bytes,
        options: dict[str, Any],
        *,
        slot: str = "import",
    ) -> str:
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise KnxError("knx_file_limit")
        if slot not in {"import", "compare_left", "compare_right"}:
            raise KnxError("knx_draft_invalid")
        stored_options = dict(options)
        if slot != "import":
            stored_options["draft_slot"] = slot
        else:
            stored_options.pop("draft_slot", None)
        encoded_options = json.dumps(stored_options, sort_keys=True)
        if len(encoded_options) > 2 * 1024 * 1024:
            raise KnxError("knx_draft_invalid")
        identifier = secrets.token_hex(24)
        with self.connection() as db:
            # One draft per purpose/session; comparison inputs never evict an
            # unsaved import. Legacy drafts without a slot belong to import.
            db.execute(
                "DELETE FROM drafts WHERE session=? "
                "AND coalesce(json_extract(options,'$.draft_slot'),'import')=?",
                (self.session, slot),
            )
            count, size = db.execute(
                "SELECT count(*),coalesce(sum(length(raw)+length(options)),0) FROM drafts"
            ).fetchone()
            if count >= MAX_DRAFTS or size + len(raw) + len(encoded_options) > MAX_DRAFT_BYTES:
                raise KnxError("knx_draft_limit")
            db.execute(
                "INSERT INTO drafts VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    self.session,
                    target,
                    revision,
                    time.time() + TTL_SECONDS,
                    raw,
                    encoded_options,
                ),
            )
        return identifier

    def load(self, identifier: object, target: str, revision: int) -> tuple[bytes, dict[str, Any]]:
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{48}", identifier):
            raise KnxError("knx_draft_invalid")
        with self.connection() as db:
            row = db.execute(
                "SELECT raw,options,target,revision FROM drafts "
                "WHERE id=? AND session=? AND expires>?",
                (identifier, self.session, time.time()),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_expired")
            if row[2] != target:
                raise KnxError("knx_target_conflict")
            if row[3] != revision:
                raise KnxError("knx_revision_conflict")
            return bytes(row[0]), json.loads(row[1])

    def discard(self, identifier: object, *, slots: tuple[str, ...] = ("import",)) -> None:
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{48}", identifier):
            raise KnxError("knx_draft_invalid")
        if not slots or not set(slots) <= {"import", "compare_left", "compare_right"}:
            raise KnxError("knx_draft_invalid")
        with self.connection() as db:
            placeholders = ",".join("?" for _ in slots)
            db.execute(
                "DELETE FROM drafts WHERE id=? AND session=? AND "
                "coalesce(json_extract(options,'$.draft_slot'),'import') IN (" + placeholders + ")",
                (identifier, self.session, *slots),
            )

    def update(self, identifier: str, options: dict[str, Any]) -> None:
        encoded = json.dumps(options, sort_keys=True)
        if len(encoded) > 2 * 1024 * 1024:
            raise KnxError("knx_draft_limit")
        with self.connection() as db:
            row = db.execute(
                "SELECT 1 FROM drafts WHERE id=? AND session=? AND expires>?",
                (identifier, self.session, time.time()),
            ).fetchone()
            if row is None:
                raise KnxError("knx_draft_expired")
            size = db.execute(
                "SELECT coalesce(sum(length(raw)+length(options)),0) FROM drafts WHERE id<>?",
                (identifier,),
            ).fetchone()[0]
            raw_size = db.execute(
                "SELECT length(raw) FROM drafts WHERE id=?", (identifier,)
            ).fetchone()[0]
            if size + raw_size + len(encoded) > MAX_DRAFT_BYTES:
                raise KnxError("knx_draft_limit")
            db.execute("UPDATE drafts SET options=? WHERE id=?", (encoded, identifier))

    def discard_comparison(self) -> None:
        """Clear this session's temporary comparison inputs, retaining imports."""
        with self.connection() as db:
            db.execute(
                "DELETE FROM drafts WHERE session=? "
                "AND json_extract(options,'$.draft_slot') IN ('compare_left','compare_right')",
                (self.session,),
            )
