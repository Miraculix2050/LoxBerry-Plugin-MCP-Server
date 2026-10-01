"""Fixed value-free availability diagnostics shared by runtime and log projection."""

from enum import StrEnum


class AvailabilityReason(StrEnum):
    UNKNOWN = "availability_unknown"
    LOCAL_RATE_LIMIT = "local_rate_limit"
    REFRESH_CONNECTION = "structure_refresh_connection"
    REFRESH_AUTH_BUSY = "structure_refresh_auth_busy"
    REFRESH_SOURCE_IP = "structure_refresh_source_ip_suppressed"
    REFRESH_PROTOCOL = "structure_refresh_protocol"
    REFRESH_TOKEN = "structure_refresh_token"
    REFRESH_TIMEOUT = "structure_refresh_timeout"
    REFRESH_UNKNOWN = "structure_refresh_unknown"


class AvailabilityPhase(StrEnum):
    UNKNOWN = "unknown"
    LOCAL_BUDGET = "local_budget"
    TOKEN = "token_lookup"
    SESSION = "session_establishment"
    VERSION = "structure_version"
    LOAD = "structure_load"
    CLOSE = "session_close"
