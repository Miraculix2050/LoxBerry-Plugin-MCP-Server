"""Native upgrade must retain a consistent event history snapshot."""

import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from mcpserver.knx.import_repository import ImportRepository
from mcpserver.knx.import_service import select_candidates
from mcpserver.knx.store import KnxStore
from mcpserver.knx.xml_adapter import NAMESPACE, parse_xml

HELPER = Path(__file__).resolve().parents[1] / "bin" / "event-history-upgrade.py"


def run(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_native_upgrade_preserves_wal_events(tmp_path: Path) -> None:
    original = tmp_path / "old" / "state-events.sqlite3"
    original.parent.mkdir()
    with closing(sqlite3.connect(original)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO events(value) VALUES ('stored')")
        db.commit()
    backup = tmp_path / "installer" / "state-events.sqlite3"
    backup.parent.mkdir()
    assert run("backup", original, backup).returncode == 0
    original.unlink()
    restored = tmp_path / "new" / "state-events.sqlite3"
    assert run("restore", backup, restored).returncode == 0
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT value FROM events").fetchall() == [("stored",)]
    assert not backup.exists()


def test_native_snapshot_preserves_knx_sources_overrides_groups_and_revision(
    tmp_path: Path,
) -> None:
    original = tmp_path / "old" / "knx" / "metadata.sqlite3"
    store = KnxStore(original)
    imported = parse_xml(
        f'<GroupAddress-Export xmlns="{NAMESPACE}">'
        '<GroupRange Name="Main" RangeStart="2048" RangeEnd="4095">'
        '<GroupAddress Address="1/2/3" Name="ETS" DPTs="DPST-1-1"/>'
        "</GroupRange></GroupAddress-Export>".encode()
    )
    repository = ImportRepository(store)
    repository.apply("target", 0, imported, select_candidates(imported), {("three_level", "1")}, {})
    store.put(
        "target",
        1,
        {"address_format": "three_level", "address": "1/2/3", "fields": {"description": "Local"}},
    )
    expected = store.page("target")
    labels = repository.selected_labels("target")
    backup = tmp_path / "installer" / "knx-metadata.sqlite3"
    backup.parent.mkdir()
    assert run("backup", original, backup).returncode == 0
    restored = tmp_path / "new" / "knx" / "metadata.sqlite3"
    restored.parent.parent.mkdir()
    assert run("restore", backup, restored).returncode == 0
    restored_store = KnxStore(restored)
    assert restored_store.page("target") == expected
    assert ImportRepository(restored_store).selected_labels("target") == labels
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT count(*) FROM ets_sources").fetchone()[0] == 1
    assert not backup.exists()


@pytest.mark.skipif(os.name != "posix", reason="native Bash upgrade hook requires POSIX")
def test_preupgrade_hook_actually_backs_up_knx_database(tmp_path: Path) -> None:
    root = HELPER.parent.parent
    installer = tmp_path / "installer"
    (installer / "bin").mkdir(parents=True)
    shutil.copy2(HELPER, installer / "bin" / HELPER.name)
    commands = tmp_path / "commands"
    commands.mkdir()
    systemctl = commands / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 1\n")
    systemctl.chmod(0o755)
    source = tmp_path / "data" / "mcpserver" / "knx" / "metadata.sqlite3"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE retained(value TEXT)")
        db.execute("INSERT INTO retained VALUES ('local metadata')")
        db.commit()
    result = subprocess.run(
        ["bash", str(root / "preupgrade.sh"), "a", "b", "mcpserver", "d", "e", str(installer)],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "LBPCONFIG": str(tmp_path / "config"),
            "LBPDATA": str(tmp_path / "data"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    backup = installer / ".mcpserver-upgrade" / "knx-metadata.sqlite3"
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM retained").fetchall() == [("local metadata",)]


def test_native_upgrade_rejects_symlink_and_destination_collision(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE events (id INTEGER)")
    link = tmp_path / "link.sqlite3"
    link.symlink_to(source)
    backup = tmp_path / "backup.sqlite3"
    assert run("backup", link, backup).returncode != 0
    assert run("backup", source, backup).returncode == 0
    assert run("backup", source, backup).returncode != 0
    assert run("restore", backup, source).returncode != 0
    assert backup.exists()


def test_native_upgrade_rejects_symlinked_restore_directory(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE events (id INTEGER)")
    outside = tmp_path / "outside"
    outside.mkdir()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "event-history").symlink_to(outside, target_is_directory=True)
    destination = plugin / "event-history" / "state-events.sqlite3"
    assert run("restore", snapshot, destination).returncode != 0
    assert snapshot.exists()
    assert not (outside / "state-events.sqlite3").exists()


@pytest.mark.skipif(
    os.rename not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"),
    reason="requires POSIX directory-FD support",
)
def test_native_upgrade_restores_through_directory_fd(tmp_path: Path, monkeypatch) -> None:
    snapshot = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(snapshot) as db:
        db.execute("CREATE TABLE events (id INTEGER)")
    destination = tmp_path / "event-history" / "state-events.sqlite3"
    restore = runpy.run_path(str(HELPER))["restore"]
    original_replace = os.replace
    directory_fds = []

    def tracked_replace(source, target, **kwargs):
        directory_fds.append(kwargs.get("dst_dir_fd"))
        return original_replace(source, target, **kwargs)

    monkeypatch.setattr(os, "replace", tracked_replace)
    restore(snapshot, destination)
    assert directory_fds and directory_fds[0] is not None
    assert destination.exists()
