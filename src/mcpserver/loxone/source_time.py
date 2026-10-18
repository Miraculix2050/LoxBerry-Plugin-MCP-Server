"""Shared conversion of documented native seconds-since-2009 timestamps."""

from datetime import UTC, datetime

LOXONE_EPOCH_UNIX = 1_230_768_000


def loxone_time(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("native timestamp is invalid")
    try:
        number = float(value)
        if not number.is_integer() or not 0 <= number <= 4_000_000_000:
            raise ValueError("native timestamp is invalid")
        return (
            datetime.fromtimestamp(LOXONE_EPOCH_UNIX + int(number), UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("native timestamp is invalid") from exc
