"""Shared administrative errors across imported and module entry points."""


class AdminError(RuntimeError):
    """A sanitized, user-actionable administrative error."""

    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code
