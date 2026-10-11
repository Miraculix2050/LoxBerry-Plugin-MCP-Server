"""OAuth scope names shared without importing the provider runtime."""

from typing import Final

READ_SCOPE: Final = "loxone:read"
MESSAGE_CONFIRM_SCOPE: Final = "loxone:messages:confirm"
CONTROL_SCOPE: Final = "loxone:control"
LOXBERRY_READ_SCOPE: Final = "loxberry:read"
HISTORY_SCOPE: Final = "loxone:history"
LOXBERRY_OPERATE_SCOPE: Final = "loxberry:operate"
# Retained as the Phase 1 source-level alias used by existing integrations.
SCOPE: Final = READ_SCOPE
SUPPORTED_SCOPES: Final = (
    READ_SCOPE,
    HISTORY_SCOPE,
    CONTROL_SCOPE,
    MESSAGE_CONFIRM_SCOPE,
    LOXBERRY_READ_SCOPE,
    LOXBERRY_OPERATE_SCOPE,
)
