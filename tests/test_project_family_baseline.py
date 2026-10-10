"""Independent authorization before immutable OAuth-family content reuse."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import mcpserver.loxone.project.service as service_module
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.service import ProjectService
from mcpserver.loxone.project.worker import process_project
from tools.benchmark_project_families import family_baseline, synthetic_project


def access(family, identity="synthetic-user", miniserver="synthetic-miniserver"):
    return SimpleNamespace(
        scopes=["loxone:read"], family_id=family, identity_id=identity, miniserver_id=miniserver
    )


def service_fixture(download=None):
    client = SimpleNamespace(
        download_project=download or AsyncMock(return_value=synthetic_project(2)),
        project_marker=AsyncMock(return_value="same-marker"),
    )
    validate = AsyncMock(return_value=True)
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(side_effect=lambda family, *_: Mock(family_id=family))),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        validate,
    )
    return service, client, validate


@pytest.mark.asyncio
async def test_synthetic_benchmark_counts_cold_and_warm_work():
    report = await family_baseline(synthetic_project(17), families=2, warm_calls=2)
    assert report["cache_entries"] == 2
    assert report["content_entries"] == 1
    assert [
        (p["phase"], p["download_count"], p["worker_count"], p["marker_count"])
        for p in report["phases"]
    ] == [
        ("cold", 1, 1, 2),
        ("warm", 2, 0, 4),
        ("cold", 1, 0, 2),
        ("warm", 2, 0, 4),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity,miniserver",
    [
        ("synthetic-user", "synthetic-miniserver"),
        ("other-user", "synthetic-miniserver"),
        ("synthetic-user", "other-miniserver"),
    ],
)
async def test_same_bytes_and_marker_do_not_skip_another_family_download(identity, miniserver):
    service, client, _ = service_fixture()
    try:
        first = await service.load_snapshot(access("first"))
        second = await service.load_snapshot(access("second", identity, miniserver))
        assert first == second
        assert (first is second) == (miniserver == "synthetic-miniserver")
        assert client.download_project.await_count == 2
        assert [call.args[0].family_id for call in client.download_project.await_args_list] == [
            "first",
            "second",
        ]
        await service.revoke("first")
        assert await service.load_snapshot(access("second", identity, miniserver)) is second
        assert client.download_project.await_count == 3
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_view", [False, True])
async def test_same_marker_permission_loss_rejects_warm_content_and_drops_only_caller(runtime_view):
    service, client, _ = service_fixture()
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "synthetic"), "same-marker", (), (), ())

    async def load(family):
        if runtime_view:
            return await service.query(
                access(family), SimpleNamespace(subject=family, structure=structure)
            )
        return await service.load_snapshot(access(family))

    try:
        await load("first")
        other = await load("second")
        client.download_project.side_effect = ProjectError("project_permission_denied")
        with pytest.raises(ProjectError, match="project_permission_denied"):
            await load("first")
        assert all(key[2] != "first" for key in service._cache)
        assert all(key[2] != "first" for key in service._content_keys)
        assert all(key[2] != "first" for key in service._views)
        client.download_project.side_effect = None
        assert await load("second") is other
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_changed_response_bytes_with_same_marker_replace_snapshot_and_view():
    service, client, _ = service_fixture()
    structure = LoxoneStructure(LoxoneIdentity("synthetic", "synthetic"), "same-marker", (), (), ())
    runtime = SimpleNamespace(subject="first", structure=structure)
    try:
        first = await service.query(access("first"), runtime)
        other = await service.load_snapshot(access("second"))
        assert first.view.snapshot is other
        client.download_project.return_value = synthetic_project(3)
        updated = await service.query(access("first"), runtime)
        assert updated is not first
        assert updated.view.snapshot is not other
        assert len(updated.view.snapshot.graph.nodes) == 3
        client.download_project.return_value = synthetic_project(2)
        assert await service.load_snapshot(access("second")) is other
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_stricter_limits_do_not_reuse_graph_parsed_under_looser_limits():
    service, _, _ = service_fixture()
    try:
        await service.load_snapshot(access("first"))
        service.limits = replace(service.limits, elements=1)
        with pytest.raises(ProjectError):
            await service.load_snapshot(access("second"))
        assert all(key[2] != "second" for key in service._cache)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_parser_epoch_change_does_not_reuse_old_content(monkeypatch):
    service, _, _ = service_fixture()
    worker = AsyncMock(wraps=process_project)
    monkeypatch.setattr(service_module, "process_project", worker)
    try:
        first = await service.load_snapshot(access("first"))
        monkeypatch.setattr(service_module, "_CONTENT_VERSION", (2, 13))
        assert await service.load_snapshot(access("second")) is not first
        assert worker.await_count == 2
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_shared_graph_accounting_and_reference_eviction_are_bounded(monkeypatch):
    service, client, _ = service_fixture()
    try:
        first = await service.load_snapshot(access("first"))
        size = service._cache_bytes()
        monkeypatch.setattr(service_module, "_MAX_CACHE_BYTES", size)
        monkeypatch.setattr(service_module, "_MAX_CACHE_ENTRIES", 2)
        assert await service.load_snapshot(access("second")) is first
        assert len(service._cache) == 2 and service._cache_bytes() == size
        assert await service.load_snapshot(access("third")) is first
        assert len(service._cache) == 2
        assert all(key[2] != "first" for key in service._content_keys)
        assert service._content_keys.keys() == service._cache.keys()
        client.download_project.return_value = synthetic_project(1)
        await service.load_snapshot(access("fourth"))
        assert service._cache_bytes() <= size
        assert service._content_keys.keys() == service._cache.keys()
        await service.close()
        assert not service._cache and not service._content_keys and not service._views
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_revocation_after_own_download_cannot_acquire_shared_reference():
    service, client, validate = service_fixture()
    denied = set()

    async def is_valid(candidate):
        return candidate.family_id not in denied

    async def download(token, *_):
        if token.family_id == "second":
            denied.add("second")
        return synthetic_project(2)

    validate.side_effect = is_valid
    try:
        first = await service.load_snapshot(access("first"))
        client.download_project.side_effect = download
        with pytest.raises(ProjectError, match="project_access_denied"):
            await service.load_snapshot(access("second"))
        assert all(key[2] != "second" for key in service._content_keys)
        assert await service.load_snapshot(access("first")) is first
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_cancellation_while_queued_does_not_cancel_other_familys_parse(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    service, client, _ = service_fixture()

    async def worker(*args, **kwargs):
        started.set()
        await release.wait()
        return await process_project(*args, **kwargs)

    monkeypatch.setattr(service_module, "process_project", worker)
    first_task = asyncio.create_task(service.load_snapshot(access("first")))
    try:
        await asyncio.wait_for(started.wait(), 5)
        second_task = asyncio.create_task(service.load_snapshot(access("second")))
        await asyncio.sleep(0)
        await service.revoke("second")
        assert second_task.cancelled()
        assert not first_task.cancelled()
        release.set()
        first = await asyncio.wait_for(first_task, 10)
        assert client.download_project.await_count == 1
        assert next(iter(service._cache.values()))[1] is first
        assert all(key[2] != "second" for key in service._content_keys)
    finally:
        release.set()
        await service.close()


@pytest.mark.asyncio
async def test_overlapping_family_loads_keep_independent_downloads():
    service, client, _ = service_fixture()
    try:
        first, second = await asyncio.gather(
            service.load_snapshot(access("first")), service.load_snapshot(access("second"))
        )
        assert first == second
        assert first is second
        assert client.download_project.await_count == 2
        assert {call.args[0].family_id for call in client.download_project.await_args_list} == {
            "first",
            "second",
        }
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_invalid_family_cannot_use_its_warm_cache_or_another_family():
    service, client, validate = service_fixture()
    try:
        first = await service.load_snapshot(access("first"))
        await service.load_snapshot(access("second"))

        async def only_first(candidate):
            return candidate.family_id == "first"

        validate.side_effect = only_first
        with pytest.raises(ProjectError, match="project_access_denied"):
            await service.load_snapshot(access("second"))
        assert await service.load_snapshot(access("first")) is first
        assert client.download_project.await_count == 3
        assert all(key[2] != "second" for key in service._cache)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_denied_family_cannot_use_another_family_graph():
    service, client, _ = service_fixture()
    try:
        first = await service.load_snapshot(access("first"))
        client.download_project.side_effect = ProjectError("project_permission_denied")
        with pytest.raises(ProjectError, match="project_permission_denied"):
            await service.load_snapshot(access("second"))
        client.download_project.side_effect = None
        assert await service.load_snapshot(access("first")) is first
        assert all(key[2] != "second" for key in service._cache)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_family_revocation_during_download_preserves_other_family():
    started = asyncio.Event()
    client_download = AsyncMock(return_value=synthetic_project(2))
    service, client, _ = service_fixture(client_download)

    async def blocked_download(*_):
        started.set()
        await asyncio.Event().wait()

    try:
        first = await service.load_snapshot(access("first"))
        client.download_project.side_effect = blocked_download
        task = asyncio.create_task(service.load_snapshot(access("second")))
        await asyncio.wait_for(started.wait(), timeout=5)
        await service.revoke("second")
        assert task.cancelled()
        client.download_project.side_effect = None
        assert await service.load_snapshot(access("first")) is first
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_same_marker_visibility_change_rebuilds_only_callers_view():
    service, client, _ = service_fixture()
    structure = LoxoneStructure(
        LoxoneIdentity("synthetic", "synthetic"),
        "same-marker",
        (),
        (),
        (Control("00000000", "Synthetic", "Switch", None, None, None, ()),),
    )
    try:
        first = await service.query(
            access("first"), SimpleNamespace(subject="first", structure=structure)
        )
        second = await service.query(
            access("second"), SimpleNamespace(subject="second", structure=structure)
        )
        changed = LoxoneStructure(structure.identity, "same-marker", (), (), ())
        refreshed = await service.query(
            access("first"), SimpleNamespace(subject="first", structure=changed)
        )
        assert refreshed is not first
        assert not refreshed.view.mapping.entries
        assert len(second.view.mapping.entries) == 1
        assert (
            await service.query(
                access("second"), SimpleNamespace(subject="second", structure=structure)
            )
            is second
        )
        assert client.download_project.await_count == 4
    finally:
        await service.close()
