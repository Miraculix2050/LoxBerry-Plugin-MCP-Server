"""Local administrator approval of one immutable, expiring MCP preview."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from mcpserver.auth.store import _lock_file, _unlock_file
from mcpserver.persistence import fsync_parent_directory

_T = TypeVar("_T")
_LOCK = threading.RLock()


class MessageApprovalStore:
    """Private cross-process bridge; never expose approval operations through MCP."""

    def __init__(self, config_path: Path) -> None:
        if not config_path.is_absolute():
            raise ValueError("Approval configuration path must be absolute")
        self.path = config_path.parent / "message-confirmations" / "approvals.json"

    def _transaction(self, operation: Callable[[dict[str, Any]], _T]) -> _T:
        with _LOCK:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.path.parent, 0o700)
            with self.path.with_suffix(".lock").open("a+b") as handle:
                os.chmod(handle.name, 0o600)
                _lock_file(handle)
                temporary = self.path.with_suffix(".tmp")
                try:
                    if self.path.exists() and self.path.stat().st_size > 8 * 1024 * 1024:
                        raise ValueError("Approval store exceeds its bound")
                    data = (
                        json.loads(self.path.read_text(encoding="utf-8"))
                        if self.path.exists()
                        else {}
                    )
                    if not isinstance(data, dict) or len(data) > 3000:
                        raise ValueError("Invalid approval store")
                    data = {k: v for k, v in data.items() if v["expires"] > time.time()}
                    result = operation(data)
                    with temporary.open("w", encoding="utf-8", newline="\n") as output:
                        os.chmod(output.name, 0o600)
                        json.dump(data, output, ensure_ascii=True)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                    fsync_parent_directory(self.path)
                    return result
                finally:
                    temporary.unlink(missing_ok=True)
                    _unlock_file(handle)

    @staticmethod
    def binding(family: tuple[str, str, str], fingerprint: str) -> str:
        return hashlib.sha256(json.dumps([family, fingerprint]).encode()).hexdigest()

    def stage(
        self, preview_id: str, binding: str, summary: dict[str, Any], *, owner: str = "local"
    ) -> None:
        def add(data: dict[str, Any]) -> None:
            for key, value in list(data.items()):
                if value["owner"] == owner and value["summary"].get("entry_uuid") == summary.get(
                    "entry_uuid"
                ):
                    del data[key]
            if sum(value["owner"] == owner for value in data.values()) >= 10:
                raise ValueError("Approval capacity exceeded for this identity")
            if len(data) >= 3000:
                raise ValueError("Approval capacity exceeded")
            data[preview_id] = {
                "binding": binding,
                "owner": owner,
                "expires": time.time() + 120,
                "challenge": secrets.token_urlsafe(32),
                "approved": False,
                "summary": summary,
            }

        self._transaction(add)

    def inspect(self, preview_id: str) -> dict[str, Any]:
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", preview_id) is None:
            raise ValueError("Invalid preview identifier")

        def lookup(data: dict[str, Any]) -> dict[str, Any]:
            record = data.get(preview_id)
            if record is None:
                raise ValueError("Preview is unavailable or expired")
            return {"preview_id": preview_id, **record["summary"], "challenge": record["challenge"]}

        return self._transaction(lookup)

    def approve(self, preview_id: str, challenge: str) -> None:
        def approve(data: dict[str, Any]) -> None:
            record = data.get(preview_id)
            if record is None or not secrets.compare_digest(record["challenge"], challenge):
                raise ValueError("Approval does not match the displayed preview")
            record["approved"] = True

        self._transaction(approve)

    def consume(self, preview_id: str, binding: str) -> bool:
        def consume(data: dict[str, Any]) -> bool:
            record = data.pop(preview_id, None)
            return bool(record and record["approved"] and record["binding"] == binding)

        return self._transaction(consume)
