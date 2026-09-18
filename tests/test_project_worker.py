import asyncio
import struct
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from mcpserver.loxone.project.graph import ProjectSnapshot
from mcpserver.loxone.project.models import ProjectError
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
async def test_worker_reports_sanitized_failure():
    with pytest.raises(ProjectError, match="project_format_invalid"):
        await process_project(b"secret invalid file")


@pytest.mark.asyncio
async def test_cache_never_skips_download_and_revocation_clears_it():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    client = SimpleNamespace(download_project=AsyncMock(return_value=sample()))
    service = ProjectService(
        client,
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    first = await service.load_snapshot(access)
    assert await service.load_snapshot(access) is first
    assert client.download_project.await_count == 2
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
        SimpleNamespace(download_project=download),
        SimpleNamespace(get=Mock(return_value=Mock())),
        SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False)),
        AsyncMock(return_value=True),
    )
    task = asyncio.create_task(service.load_snapshot(access))
    await started.wait()
    await service.revoke("f")
    assert task.cancelled()
    assert not service._tasks
