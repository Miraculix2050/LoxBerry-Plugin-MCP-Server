"""Keep local chart queries independent of the project runtime import graph."""

from __future__ import annotations

import subprocess
import sys


def test_chart_admin_import_does_not_load_project_runtime() -> None:
    probe = (
        "import sys\n"
        "import mcpserver.event_history_admin\n"
        "assert 'mcpserver.loxone.runtime' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
