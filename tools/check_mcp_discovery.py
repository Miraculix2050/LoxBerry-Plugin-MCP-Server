"""Compare bounded local tools/list captures without networking or printing schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mcpserver.discovery import MAX_DISCOVERY_BYTES, compare_discovery


def read_capture(path: Path) -> object:
    with path.open("rb") as stream:
        raw = stream.read(MAX_DISCOVERY_BYTES + 1)
    if len(raw) > MAX_DISCOVERY_BYTES:
        raise ValueError("discovery_file_limit")
    return json.loads(raw.decode("utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--observed", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = compare_discovery(read_capture(args.reference), read_capture(args.observed))
    except (OSError, UnicodeError, ValueError, RecursionError):
        print(json.dumps({"status": "invalid", "error": "discovery_capture_invalid"}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "equal" else 1


if __name__ == "__main__":
    raise SystemExit(main())
