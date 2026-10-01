"""Development-only browser measurement privacy/timing and fixture regressions."""

import shutil
import subprocess
from pathlib import Path


def test_chart_measurement_harness():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node is not None, "Node.js is required"
    result = subprocess.run(
        [node, "--test", "tests/js/chart-measurement.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
