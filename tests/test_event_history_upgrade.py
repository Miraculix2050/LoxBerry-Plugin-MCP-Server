"""Native upgrade must retain a consistent event history snapshot."""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

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
