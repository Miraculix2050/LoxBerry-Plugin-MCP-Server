"""Public package version stays compatible without eager metadata discovery."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_admin_import_defer_version_metadata_and_cache_first_use():
    code = """
import sys
import mcpserver
import mcpserver.admin
import mcpserver.knx.admin
import mcpserver.knx.admin_bridge
assert 'asyncio' not in sys.modules
assert 'urllib.request' not in sys.modules
assert 'importlib.metadata' not in sys.modules
try:
    mcpserver.not_a_public_attribute
except AttributeError:
    pass
else:
    raise AssertionError('unknown package attribute accepted')
assert 'importlib.metadata' not in sys.modules
import importlib.metadata
calls = []
def version(name):
    calls.append(name)
    return '1.2.3'
importlib.metadata.version = version
from mcpserver import __version__
assert __version__ == '1.2.3'
assert mcpserver.__version__ == '1.2.3'
assert calls == ['loxberry-mcpserver']
print('ok')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        check=True,
    )
    assert result.stdout.strip() == "ok"


def test_missing_distribution_preserves_release_fallback(monkeypatch):
    import importlib.metadata

    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)
    namespace = {"__name__": "synthetic_package"}
    source = (ROOT / "src/mcpserver/__init__.py").read_text(encoding="utf-8")
    exec(compile(source, "synthetic_package", "exec"), namespace)
    expected = __import__("re").search(r'__version__ = "([^\"]+)"', source)[1]
    assert namespace["__getattr__"]("__version__") == expected
    assert namespace["__version__"] == expected


def test_public_version_matches_installed_distribution():
    from importlib.metadata import version

    from mcpserver import __version__

    assert __version__ == version("loxberry-mcpserver")
