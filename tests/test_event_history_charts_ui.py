"""Exercise the shipped Event History chart tab in a deterministic DOM."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_event_history_charts_dom() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for chart DOM tests"
    assert (ROOT / "node_modules" / "jsdom").is_dir(), "Run npm ci --ignore-scripts"
    result = subprocess.run(
        [node, "--test", "tests/js/event-history-charts.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
