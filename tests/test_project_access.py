from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from mcpserver.loxone.client import LoxoneClient, LoxoneToken, MiniserverEndpoint
from mcpserver.loxone.project.models import ProjectError, ProjectLimits
from mcpserver.loxone.project.service import ProjectService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "permission_denied"),
        (403, "permission_denied"),
        (302, "http_rejected"),
        (404, "http_rejected"),
    ],
)
async def test_http_rejection_is_sanitized_and_not_retried(monkeypatch, status, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, headers={"Location": "https://foreign.invalid"}, text="secret"
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "mcpserver.loxone.client.httpx.AsyncClient",
        lambda **kw: original(**kw, transport=httpx.MockTransport(respond)),
    )
    client = LoxoneClient(MiniserverEndpoint.parse("https://example.com"), client_uuid=uuid4())
    with pytest.raises(ProjectError, match=expected) as error:
        await client.download_project(LoxoneToken("secret", "private", "", "SHA256", 9999999999))
    assert "secret" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_http_stream_is_bounded(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, stream=httpx.ByteStream(b"x" * 12))
    )
    monkeypatch.setattr(
        "mcpserver.loxone.client.httpx.AsyncClient",
        lambda **kw: original(**kw, transport=transport),
    )
    client = LoxoneClient(MiniserverEndpoint.parse("https://example.com"), client_uuid=uuid4())
    with pytest.raises(ProjectError, match="download_limit"):
        await client.download_project(
            LoxoneToken("s", "u", "", "SHA256", 9999999999), ProjectLimits(download_bytes=4)
        )


@pytest.mark.asyncio
async def test_project_marker_uses_authenticated_session_and_closes_it(monkeypatch):
    client = LoxoneClient(MiniserverEndpoint.parse("https://example.com"), client_uuid=uuid4())
    session = SimpleNamespace(
        structure_version=AsyncMock(return_value="revision"), close=AsyncMock()
    )
    monkeypatch.setattr(client, "open_session", AsyncMock(return_value=session))
    token = LoxoneToken("secret", "reader", "", "SHA256", 9999999999)
    assert await client.project_marker(token) == "revision"
    client.open_session.assert_awaited_once_with(token)
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_service_uses_coordinated_marker_reader():
    client = SimpleNamespace(project_marker=AsyncMock(side_effect=AssertionError("raw login")))
    reader = AsyncMock(return_value="revision")
    service = ProjectService(
        client,
        SimpleNamespace(),
        SimpleNamespace(),
        AsyncMock(return_value=True),
        marker_reader=reader,
    )
    token = LoxoneToken("opaque", "reader", "", "SHA256", 9_999_999_999)

    assert await service._marker(token) == "revision"
    reader.assert_awaited_once_with(token)
    client.project_marker.assert_not_awaited()


@pytest.mark.asyncio
async def test_revocation_after_download_prevents_project_result():
    access = SimpleNamespace(
        scopes=["loxone:read"], family_id="f", miniserver_id="m", identity_id="i"
    )
    token = Mock()
    client = SimpleNamespace(download_project=AsyncMock(return_value=b"\xee\xcc\xbb\xaa"))
    tokens = SimpleNamespace(get=Mock(return_value=token))
    health = SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=False))
    validate = AsyncMock(side_effect=[True, False])
    service = ProjectService(client, tokens, health, validate)
    with pytest.raises(ProjectError, match="access_denied"):
        await service.load_bundle(access)
    token.destroy.assert_called_once()
    tokens.get.assert_called_once_with("f", "m", "i")
