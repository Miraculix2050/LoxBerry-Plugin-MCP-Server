"""Run the shipped Explorer page in the deterministic Node DOM harness."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_explorer_dom_and_integration_flows() -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for Explorer DOM tests"
    assert (ROOT / "node_modules" / "jsdom").is_dir(), (
        "Explorer DOM tests require npm ci --ignore-scripts"
    )
    result = subprocess.run(
        [node, "--test", "tests/js/explorer-behavior.test.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
