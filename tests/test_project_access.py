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
