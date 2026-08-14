"""Persisted, non-secret health state for one Loxone token binding."""

from __future__ import annotations

from dataclasses import dataclass

from mcpserver.auth.store import AtomicJsonAuthStore

MAX_REJECTED_AUTHENTICATIONS = 3
_REJECTION_KIND = "token_authentication"


@dataclass(frozen=True, slots=True)
class LoxoneTokenHealth:
    """Sanitized state exposed to the local administrator."""

    confirmation_required: bool
    rejected_authentications: int


class LoxoneTokenHealthStore:
    """Fail closed per OAuth family after repeated rejected token authentication."""

    def __init__(self, auth_store: AtomicJsonAuthStore) -> None:
        self._auth_store = auth_store

    def get(self, family_id: str) -> LoxoneTokenHealth:
        document = self._auth_store.snapshot()
        record = document.get("families", {}).get(family_id)
        if not isinstance(record, dict):
            return LoxoneTokenHealth(False, 0)
        count = record.get("loxone_token_rejections", 0)
        current = record.get("loxone_token_rejection_kind") == _REJECTION_KIND
        return LoxoneTokenHealth(
            current and record.get("loxone_token_confirmation_required") is True,
            count if current and isinstance(count, int) and count >= 0 else 0,
        )

    def record_rejected_authentication(self, family_id: str) -> LoxoneTokenHealth:
        def mutate(document: dict[str, object]) -> LoxoneTokenHealth:
            families = document.get("families")
            record = families.get(family_id) if isinstance(families, dict) else None
            if not isinstance(record, dict) or record.get("revoked") is True:
                return LoxoneTokenHealth(False, 0)
            previous = (
                record.get("loxone_token_rejections", 0)
                if record.get("loxone_token_rejection_kind") == _REJECTION_KIND
                else 0
            )
            count = previous if isinstance(previous, int) and previous >= 0 else 0
            count = min(MAX_REJECTED_AUTHENTICATIONS, count + 1)
            record["loxone_token_rejection_kind"] = _REJECTION_KIND
            record["loxone_token_rejections"] = count
            if count >= MAX_REJECTED_AUTHENTICATIONS:
                record["loxone_token_confirmation_required"] = True
            return LoxoneTokenHealth(
                record.get("loxone_token_confirmation_required") is True,
                count,
            )

        return self._auth_store.mutate(mutate)

    def record_successful_authentication(self, family_id: str) -> None:
        def mutate(document: dict[str, object]) -> None:
            families = document.get("families")
            record = families.get(family_id) if isinstance(families, dict) else None
            if isinstance(record, dict):
                record.pop("loxone_token_rejections", None)
                record.pop("loxone_token_rejection_kind", None)
                record.pop("loxone_token_confirmation_required", None)

        self._auth_store.mutate(mutate)

    def confirm_retry(self, family_id: str) -> bool:
        def mutate(document: dict[str, object]) -> bool:
            families = document.get("families")
            record = families.get(family_id) if isinstance(families, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("revoked") is True
                or record.get("loxone_token_confirmation_required") is not True
                or record.get("loxone_token_rejection_kind") != _REJECTION_KIND
            ):
                return False
            record.pop("loxone_token_rejections", None)
            record.pop("loxone_token_rejection_kind", None)
            record.pop("loxone_token_confirmation_required", None)
            return True

        return self._auth_store.mutate(mutate)
