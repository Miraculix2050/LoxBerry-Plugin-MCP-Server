"""Generate or check the complete compatibility guide from canonical modules."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcpserver.skill_delivery import render_full_guide  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "src/mcpserver/skills/using-loxberry-mcp/SKILL.md"
    content = render_full_guide()
    if args.check:
        return 0 if target.read_text(encoding="utf-8") == content else 1
    target.write_text(content, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
