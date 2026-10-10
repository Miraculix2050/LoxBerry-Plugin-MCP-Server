import asyncio
import struct
import zipfile
import zlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import mcpserver.loxone.project.service as service_module
from mcpserver.loxone.client import LoxoneConnectionError, LoxoneTokenAuthenticationRejected
from mcpserver.loxone.models import Control, LoxoneIdentity, LoxoneStructure
from mcpserver.loxone.project.graph import ProjectSnapshot
from mcpserver.loxone.project.mapping import ProjectView, map_runtime
from mcpserver.loxone.project.models import ProjectError
from mcpserver.loxone.project.query import ProjectQuery
from mcpserver.loxone.project.service import ProjectService
from mcpserver.loxone.project.worker import process_project


def sample():
    plain = b'<C U="a"/>'
    packed = bytes([len(plain) << 4]) + plain
    return struct.pack("<IIII", 0xAABBCCEE, len(packed), len(plain), zlib.crc32(plain)) + packed


@pytest.mark.asyncio
async def test_real_worker_returns_immutable_snapshot():
    result, size = await process_project(sample())
    assert isinstance(result, ProjectSnapshot)
    assert len(result.graph.nodes) == 1
    assert size > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("target_count", [0, 1, 2])
@pytest.mark.parametrize("reference_first", [False, True])
async def test_archive_worker_and_query_resolve_only_unique_cross_model_outputrefs(
    target_count, reference_first
):
    reference = b'<P><C Type="OutputRef" Ref="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/></P>'
    target = (
        b"<P>"
        + b'<C Type="VirtualOutCmd" U="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"/>' * target_count
        + b"</P>"
    )
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for name, plain in zip(
            ("a.LoxCC", "b.LoxCC"),
            (reference, target) if reference_first else (target, reference),
            strict=True,
        ):
            packed = (
                bytes([len(plain) << 4]) if len(plain) < 15 else bytes([0xF0, len(plain) - 15])
            ) + plain
            output.writestr(
                name,
                struct.pack("<IIII", 0xAABBCCEE, len(packed), len(plain), zlib.crc32(plain))
                + packed,
            )
    snapshot, _ = await process_project(archive.getvalue())
    assert snapshot.model_version == 13
    structure = SimpleNamespace(last_modified="fixture", controls=())
    query = ProjectQuery(ProjectView(snapshot, map_runtime(snapshot, structure)), {})
    node = next(n for n in snapshot.graph.nodes if n.block_type == "OutputRef")
    assert query.status()["project_parts"] == 2
    assert query.status()["unresolved_relationships"] == (0 if target_count == 1 else 1)
    trace = query.trace(node, direction="upstream", max_depth=1, max_nodes=10)
    assert not trace["truncated"]
    if target_count == 1:
        (edge,) = trace["edges"]
        assert edge["kind"] == "reference" and edge["target"] == node.key
        assert edge["source"].split(":")[0] != node.project
        assert not trace["unresolved_relationships"]
        assert query.describe(node, limit=10)["relationships"][0]["kind"] == "reference"
    else:
        assert not trace["edges"]
        assert trace["unresolved_relationships"]


@pytest.mark.asyncio
async def test_worker_reports_sanitized_failure():
    with pytest.raises(ProjectError, match="project_format_invalid"):
        await process_project(b"secret invalid file")


@pytest.mark.asyncio
async def test_cache_uses_authenticated_marker_and_revocation_clears_it():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    first = await service.load_snapshot(access)
    assert await service.load_snapshot(access) is first
    assert client.download_project.await_count == 2
    assert service.cache_counts["hit"] == 1
    client.project_marker.return_value = "v2"
    assert await service.load_snapshot(access) is not first
    assert client.download_project.await_count == 3
    assert service.cache_counts["invalidate"] == 1
    await service.revoke("f")
    assert not service._cache
    client.download_project.side_effect = ProjectError("project_permission_denied")
    with pytest.raises(ProjectError, match="permission_denied"):
        await service.load_snapshot(access)
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_revoke_cancels_an_active_download():
    started = asyncio.Event()

    async def download(*args):
        started.set()
        await asyncio.Event().wait()

    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    service = ProjectService(
        SimpleNamespace(download_project=download, project_marker=AsyncMock(return_value="v1")),
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    task = asyncio.create_task(service.load_snapshot(access))
    await started.wait()
    await service.revoke("f")
    assert task.cancelled()
    assert not service._tasks


@pytest.mark.asyncio
async def test_cache_fails_closed_on_marker_error_and_project_change():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(side_effect=["v1", "v1", "v1", "v1", "v1", "v2"]),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    await service.load_snapshot(access)
    assert await service.load_snapshot(access)
    with pytest.raises(ProjectError, match="project_changed_during_load"):
        await service.load_snapshot(access)
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_marker_failure_evicts_cached_graph():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    await service.load_snapshot(access)
    client.project_marker.side_effect = LoxoneConnectionError("unavailable")
    with pytest.raises(ProjectError, match="project_transport_error"):
        await service.load_snapshot(access)
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", ["", "x" * 129])
async def test_invalid_project_marker_never_downloads_or_returns_graph(marker):
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value=marker),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    with pytest.raises(ProjectError, match="project_marker_invalid"):
        await service.load_snapshot(access)
    client.download_project.assert_not_awaited()
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_rejected_remote_auth_never_returns_cached_graph():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    await service.load_snapshot(access)
    client.project_marker.side_effect = LoxoneTokenAuthenticationRejected("rejected")
    with pytest.raises(ProjectError, match="project_permission_denied"):
        await service.load_snapshot(access)
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_concurrent_calls_download_independently_and_parse_once():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    first, second = await asyncio.gather(
        service.load_snapshot(access), service.load_snapshot(access)
    )
    assert first is second
    assert client.download_project.await_count == 2
    await service.close()


@pytest.mark.asyncio
async def test_revoked_access_never_returns_cached_graph():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    validate = AsyncMock(return_value=True)
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        validate,
    )
    await service.load_snapshot(access)
    validate.return_value = False
    with pytest.raises(ProjectError, match="project_access_denied"):
        await service.load_snapshot(access)
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_oversized_graph_is_not_cached(monkeypatch):
    monkeypatch.setattr(service_module, "_MAX_CACHE_BYTES", 1)
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    await service.load_snapshot(access)
    await service.load_snapshot(access)
    assert client.download_project.await_count == 2
    assert not service._cache
    await service.close()


@pytest.mark.asyncio
async def test_same_marker_and_visible_structure_reuse_mapping_and_query():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "v1", (), (), ())
    runtime = SimpleNamespace(subject="f", structure=structure)
    first = await service.query(access, runtime)
    second = await service.query(
        access,
        SimpleNamespace(
            subject="f",
            structure=LoxoneStructure(LoxoneIdentity("reader", "serial"), "v1", (), (), ()),
        ),
    )
    assert second is first
    assert second.view.marker == "v1"
    assert client.download_project.await_count == 2
    changed_structure = LoxoneStructure(
        LoxoneIdentity("reader", "serial"),
        "v1",
        (),
        (),
        (Control("control-1", "Visible", "Switch", None, None, None, ()),),
    )
    changed = await service.query(access, SimpleNamespace(subject="f", structure=changed_structure))
    assert changed is not first
    assert changed.view.mapping.structure_fingerprint != first.view.mapping.structure_fingerprint
    await service.revoke("f")
    assert not service._views
    await service.close()


@pytest.mark.asyncio
async def test_warm_query_rechecks_access_around_download_and_rejects_revocation():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    validate = AsyncMock(return_value=True)
    client = SimpleNamespace(
        download_project=AsyncMock(return_value=sample()),
        project_marker=AsyncMock(return_value="v1"),
    )
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        validate,
    )
    structure = LoxoneStructure(LoxoneIdentity("reader", "serial"), "v1", (), (), ())
    runtime = SimpleNamespace(subject="f", structure=structure)
    await service.query(access, runtime)

    validate.reset_mock()
    await service.query(access, runtime)
    assert validate.await_count == 4

    validate.return_value = False
    with pytest.raises(ProjectError, match="project_access_denied"):
        await service.query(access, runtime)
    assert not service._cache
    assert not service._views
    await service.close()
