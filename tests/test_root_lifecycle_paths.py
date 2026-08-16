from __future__ import annotations

import os
import runpy
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX dir_fd semantics")


def _helpers() -> dict[str, Any]:
    return runpy.run_path(
        str(ROOT / "bin" / "root-lifecycle-paths.py"), run_name="root_lifecycle_paths"
    )


def _plugin_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "loxberry"
    data = home / "data" / "plugins" / "mcpserver"
    log = home / "log" / "plugins" / "mcpserver"
    data.mkdir(parents=True)
    log.mkdir(parents=True)
    return home, data, log


def _call(helper: Callable[..., None], home: Path, *args: str) -> None:
    helper(
        str(home),
        "mcpserver",
        *args,
        owner_uid=os.getuid(),
        owner_gid=os.getgid(),
        **({"root_uid": os.getuid()} if helper.__name__ == "prepare_install_key" else {}),
    )


def test_lifecycle_helper_preserves_upgrade_key_and_sets_modes(tmp_path: Path) -> None:
    helpers = _helpers()
    home, data, log = _plugin_tree(tmp_path)
    auth = data / "auth"
    auth.mkdir()
    key = auth / "install.key"
    original = os.urandom(32)
    key.write_bytes(original)
    key.chmod(0o600)

    _call(helpers["prepare_private_directory"], home, "statistics-cache")
    _call(helpers["prepare_install_key"], home)
    _call(helpers["prepare_service_log"], home)

    assert key.read_bytes() == original
    assert stat.S_IMODE(key.stat().st_mode) == 0o640
    assert stat.S_IMODE((data / "statistics-cache").stat().st_mode) == 0o700
    assert stat.S_IMODE((log / "service.log").stat().st_mode) == 0o640


@pytest.mark.parametrize("target_name", ["statistics-cache", "auth"])
def test_lifecycle_helper_rejects_symlinked_private_paths(tmp_path: Path, target_name: str) -> None:
    helpers = _helpers()
    home, data, _ = _plugin_tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (data / target_name).symlink_to(outside, target_is_directory=True)

    helper = (
        helpers["prepare_private_directory"]
        if target_name == "statistics-cache"
        else helpers["prepare_install_key"]
    )
    args = ("statistics-cache",) if target_name == "statistics-cache" else ()
    with pytest.raises(OSError):
        _call(helper, home, *args)

    assert list(outside.iterdir()) == []


def test_lifecycle_helper_rejects_symlinked_key(tmp_path: Path) -> None:
    helpers = _helpers()
    home, data, _ = _plugin_tree(tmp_path)
    auth = data / "auth"
    auth.mkdir()
    outside = tmp_path / "outside-key"
    outside.write_bytes(os.urandom(32))
    (auth / "install.key").symlink_to(outside)

    with pytest.raises(OSError):
        _call(helpers["prepare_install_key"], home)

    assert outside.stat().st_nlink == 1


def test_lifecycle_helper_rejects_non_regular_service_log(tmp_path: Path) -> None:
    helpers = _helpers()
    home, _, log = _plugin_tree(tmp_path)
    (log / "service.log").mkdir()

    with pytest.raises(OSError):
        _call(helpers["prepare_service_log"], home)


def test_lifecycle_helper_rejects_symlinked_plugin_prefix(tmp_path: Path) -> None:
    helpers = _helpers()
    home, data, _ = _plugin_tree(tmp_path)
    outside = tmp_path / "outside-plugin"
    outside.mkdir()
    data.rmdir()
    data.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        _call(helpers["prepare_private_directory"], home, "statistics-cache")

    assert list(outside.iterdir()) == []
