"""Generate the static HTML and JSON MCP tool schema reference."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcpserver.schema_reference import write_schema_reference  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = document.get("project", {}).get("version")
    if not isinstance(version, str):
        raise SystemExit("project version is missing")
    for path in write_schema_reference(args.output_root.resolve(), version):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
