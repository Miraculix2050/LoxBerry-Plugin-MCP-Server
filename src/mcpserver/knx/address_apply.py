"""Atomic selected-address overrides and bounded, owner-bound receipts."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from .model import KnxError, metadata, text
from .store import KnxStore

RECEIPT_LIMIT = 1024
RECEIPT_TTL = 7 * 24 * 60 * 60


def current_time() -> float:
    return time.time()


def receipt(
    db: sqlite3.Connection, owner: str, target: str, request_key: str, digest: str, now: int
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT digest,substr(result,1,4097),expires,length(result) FROM local_apply_receipts "
        "WHERE owner=? AND target=? AND request_key=?",
        (owner, target, request_key),
    ).fetchone()
    if row is None:
        return None
    if type(row[2]) is not int or type(row[3]) is not int or row[3] > 4096:
        raise KnxError("knx_storage_failed")
    if row[0] != digest:
        raise KnxError("knx_correction_request_conflict")
    if row[2] <= now:
        raise KnxError("knx_correction_receipt_expired")
    try:
        result = json.loads(row[1])
    except (ValueError, TypeError):
        raise KnxError("knx_storage_failed") from None
    if not isinstance(result, dict):
        raise KnxError("knx_storage_failed")
    if (
        set(result)
        != {
            "destination",
            "storage",
            "catalog_revision",
            "selected_changes",
            "changed_addresses",
            "loxone_written",
            "import_written",
            "exports_file",
        }
        or result["destination"] != "local_metadata"
        or result["storage"] != "addresses"
        or type(result["catalog_revision"]) is not int
        or result["catalog_revision"] < 0
        or type(result["selected_changes"]) is not int
        or not 1 <= result["selected_changes"] <= 50
        or type(result["changed_addresses"]) is not int
        or not 0 <= result["changed_addresses"] <= result["selected_changes"]
        or any(
            result[key] is not False
            for key in (
                "loxone_written",
                "import_written",
                "exports_file",
            )
        )
    ):
        raise KnxError("knx_storage_failed")
    return result


def apply_addresses(
    store: KnxStore,
    owner: str,
    target: str,
    request_key: str,
    digest: str,
    expected: int,
    changes: list[dict[str, Any]],
    *,
    now: int,
    expires_at: float,
    authorize_effect: Callable[[], object],
) -> dict[str, Any]:
    """Commit selected field effects and their authoritative receipt together.

    Caller holds the configuration lock and freshly validates the owned draft,
    its decisions and all target/manual/project bindings before this call.
    """
    if (
        not isinstance(owner, str)
        or not isinstance(request_key, str)
        or not isinstance(digest, str)
        or type(now) is not int
        or type(expires_at) not in {int, float}
        or not math.isfinite(expires_at)
        or not re.fullmatch(r"[0-9a-f]{64}", owner)
        or not re.fullmatch(r"[0-9a-f]{32}", request_key)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(changes, list)
        or not 1 <= len(changes) <= 50
    ):
        raise KnxError("knx_correction_invalid")
    selected: dict[int, dict[str, dict[str, Any]]] = {}
    for change in changes:
        if not isinstance(change, dict):
            raise KnxError("knx_correction_invalid")
        number, field = change.get("address_id"), change.get("field")
        operation = change.get("operation")
        if (
            type(number) is not int
            or not 0 <= number < 65536
            or change.get("destination") != "local_metadata"
            or change.get("kind") != "address"
            or change.get("decision") != "accepted"
            or not isinstance(field, str)
            or field not in {"name", "description"}
            or not isinstance(operation, str)
            or operation not in {"set", "remove_override"}
            or (operation == "set") != ("value" in change)
            or field in selected.get(number, {})
        ):
            raise KnxError("knx_correction_invalid")
        if operation == "set":
            text(change["value"], 255 if field == "name" else 4096, empty=field == "description")
        selected.setdefault(number, {})[field] = change
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        old = receipt(db, owner, target, request_key, digest, now)
        if old is not None:
            return old
        store.check(db, target, expected)
        marks = ",".join("?" for _ in selected)
        rows = db.execute(
            "SELECT a.address,a.imported,a.overrides,s.address FROM addresses a "
            "LEFT JOIN ets_sources s ON s.target=a.target AND s.address=a.address "
            "WHERE a.target=? AND a.address IN (" + marks + ")",
            (target, *selected),
        ).fetchall()
        if len(rows) != len(selected):
            raise KnxError("knx_correction_address_unavailable")
        updates: list[tuple[str, str, int]] = []
        for number, imported_raw, overrides_raw, source_address in rows:
            try:
                imported = metadata(json.loads(imported_raw))
                original = metadata(json.loads(overrides_raw))
            except (ValueError, TypeError):
                raise KnxError("knx_storage_failed") from None
            merged = dict(original)
            for field, change in selected[number].items():
                if change["operation"] == "set":
                    merged[field] = change["value"]
                else:
                    merged.pop(field, None)
            metadata(
                {**imported, **merged},
                require_name=source_address is None and not imported,
            )
            if merged != original:
                updates.append((json.dumps(merged, sort_keys=True), target, number))
        # Validate the entire batch before effects. Receipt housekeeping cannot
        # be mistaken for a catalog mutation and rolls back with any failure.
        db.execute("DELETE FROM local_apply_receipts WHERE expires<=?", (now,))
        if db.execute("SELECT count(*) FROM local_apply_receipts").fetchone()[0] >= RECEIPT_LIMIT:
            raise KnxError("knx_correction_receipt_limit")
        # A lock wait must not carry expired draft consent or revoked grants
        # across the effect boundary. The caller still reauthorizes afterwards.
        if expires_at <= current_time():
            raise KnxError("knx_draft_unavailable")
        authorize_effect()
        if expires_at <= current_time():
            raise KnxError("knx_draft_unavailable")
        db.executemany("UPDATE addresses SET overrides=? WHERE target=? AND address=?", updates)
        if updates:
            db.execute("UPDATE targets SET revision=revision+1 WHERE target=?", (target,))
        result = {
            "destination": "local_metadata",
            "storage": "addresses",
            "catalog_revision": store.revision(db, target),
            "selected_changes": len(changes),
            "changed_addresses": len(updates),
            "loxone_written": False,
            "import_written": False,
            "exports_file": False,
        }
        db.execute(
            "INSERT INTO local_apply_receipts VALUES(?,?,?,?,?,?)",
            (owner, target, request_key, digest, json.dumps(result), now + RECEIPT_TTL),
        )
        db.commit()
        return result
