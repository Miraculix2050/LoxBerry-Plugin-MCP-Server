"""Cross-process Admin emergency-stop option cache behavior."""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from uuid import UUID

import pytest

from mcpserver.emergency_options_cache import EmergencyOptionsCache

_UUID = str(UUID("00000000-0000-0000-0000-000000000123"))


def _refresh_worker(
    auth_path: str, marker: str, start: object, results: object, available: bool
) -> None:
    cache = EmergencyOptionsCache(Path(auth_path), "profile-a")
    start.wait()

    def discover() -> dict[str, object]:
        with Path(marker).open("a", encoding="utf-8") as handle:
            handle.write("discovery\n")
        time.sleep(0.3)
        return (
            {"status": "available", "options": [{"uuid": _UUID, "name": "Signal"}]}
            if available
            else {
                "status": "unavailable",
                "options": [],
                "discovery_failure_code": "connection_failed",
            }
        )

    results.put(cache.refresh(discover))


def _lock_worker(auth_path: str, acquired: object) -> None:
    cache = EmergencyOptionsCache(Path(auth_path), "profile-a")
    with cache._locked():
        acquired.set()
        time.sleep(30)


@pytest.mark.parametrize("available", [True, False])
def test_concurrent_admin_refreshes_share_one_discovery(tmp_path: Path, available: bool) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    marker = tmp_path / "attempts.txt"
    auth_path = tmp_path / "auth.json"
    processes = [
        context.Process(
            target=_refresh_worker, args=(str(auth_path), str(marker), start, results, available)
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
        assert process.exitcode == 0
    assert marker.read_text(encoding="utf-8").splitlines() == ["discovery"]
    expected_status = "available" if available else "unavailable"
    assert all(results.get(timeout=2)["status"] == expected_status for _ in processes)


def test_last_good_options_survive_failed_refresh_and_profile_change(tmp_path: Path) -> None:
    cache = EmergencyOptionsCache(tmp_path / "auth.json", "profile-a")
    assert cache.response(cache.read(), cached_only=True) == {"status": "not_loaded", "options": []}
    cache.refresh(lambda: {"status": "available", "options": [{"uuid": _UUID, "name": "Signal"}]})
    failed = cache.refresh(
        lambda: {
            "status": "unavailable",
            "options": [],
            "discovery_failure_code": "authentication_busy",
            "retry_not_before": 1234567890,
        }
    )
    assert failed["status"] == "unavailable"
    assert failed["options"] == [{"uuid": _UUID, "name": "Signal"}]
    assert failed["retry_not_before"] == 1234567890
    cached = cache.response(cache.read(), cached_only=True)
    assert cached["status"] == "available"
    assert cached["stale"] is True
    assert EmergencyOptionsCache(tmp_path / "auth.json", "profile-b").read() is None
    if os.name != "nt":
        assert cache.path.stat().st_mode & 0o077 == 0


def test_empty_result_is_a_valid_cached_list(tmp_path: Path) -> None:
    cache = EmergencyOptionsCache(tmp_path / "auth.json", "profile-a")
    cache.refresh(lambda: {"status": "available", "options": []})
    assert cache.response(cache.read(), cached_only=True) == {
        "status": "available",
        "options": [],
        "cached": True,
        "stale": False,
    }


def test_opaque_structure_identifiers_are_preserved(tmp_path: Path) -> None:
    cache = EmergencyOptionsCache(tmp_path / "auth.json", "profile-a")
    cache.refresh(
        lambda: {"status": "available", "options": [{"uuid": "control-1", "name": "Signal"}]}
    )
    assert cache.response(cache.read(), cached_only=True)["options"] == [
        {"uuid": "control-1", "name": "Signal"}
    ]


def test_largest_ordinary_option_list_fits_and_oversized_list_is_rejected(tmp_path: Path) -> None:
    cache = EmergencyOptionsCache(tmp_path / "auth.json", "profile-a")
    options = [{"uuid": f"{number:036d}", "name": "Signal " + "x" * 43} for number in range(20_000)]
    assert (
        cache.refresh(lambda: {"status": "available", "options": options})["status"] == "available"
    )
    assert len(cache.read()["options"]) == 20_000
    oversized = [{"uuid": f"{number:036d}", "name": "x" * 512} for number in range(20_000)]
    with pytest.raises(ValueError, match="invalid emergency-stop discovery options"):
        cache.refresh(lambda: {"status": "available", "options": oversized})
    with pytest.raises(ValueError, match="invalid emergency-stop discovery options"):
        cache.refresh(
            lambda: {"status": "available", "options": [{"uuid": _UUID, "name": "\ud800"}]}
        )


def test_crashed_refresh_worker_releases_cross_process_lock(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    auth_path = tmp_path / "auth.json"
    process = context.Process(target=_lock_worker, args=(str(auth_path), acquired))
    process.start()
    assert acquired.wait(timeout=5)
    process.terminate()
    process.join(timeout=5)
    assert not process.is_alive()
    cache = EmergencyOptionsCache(auth_path, "profile-a")
    assert cache.refresh(lambda: {"status": "available", "options": []})["status"] == "available"


def test_invalid_or_oversized_cache_is_ignored(tmp_path: Path) -> None:
    cache = EmergencyOptionsCache(tmp_path / "auth.json", "profile-a")
    cache.path.write_text("{" + "x" * (2 * 1024 * 1024), encoding="utf-8")
    assert cache.read() is None
    cache.path.write_text('{"schema":1,"profile":"profile-a","options":[]}', encoding="utf-8")
    assert cache.read() is None
