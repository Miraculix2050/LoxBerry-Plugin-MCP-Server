"""Isolation baseline for #379 before any content sharing is considered."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.service import ProjectService
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
    assert [
        (p["phase"], p["download_count"], p["worker_count"], p["marker_count"])
        for p in report["phases"]
    ] == [
        ("cold", 1, 1, 2),
        ("warm", 0, 0, 2),
        ("cold", 1, 1, 2),
        ("warm", 0, 0, 2),
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
        assert first is not second
        assert client.download_project.await_count == 2
        assert [call.args[0].family_id for call in client.download_project.await_args_list] == [
            "first",
            "second",
        ]
        await service.revoke("first")
        assert await service.load_snapshot(access("second", identity, miniserver)) is second
        assert client.download_project.await_count == 2
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_overlapping_family_loads_keep_independent_downloads():
    service, client, _ = service_fixture()
    try:
        first, second = await asyncio.gather(
            service.load_snapshot(access("first")), service.load_snapshot(access("second"))
        )
        assert first == second
        assert first is not second
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
        assert client.download_project.await_count == 2
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
        assert client.download_project.await_count == 2
    finally:
        await service.close()
