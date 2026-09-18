import io
import struct
import zipfile
from types import SimpleNamespace

import httpx
import pytest

from tools import diagnose_loxcc_access as diagnostic
from tools.diagnose_loxcc_access import MAX_DECODED_BYTES, classify, select_family


def test_header_is_evidence_not_full_decode():
    result = classify(struct.pack("<IIII", 0xAABBCCEE, 1, 12, 0) + b"x")
    assert result["result"] == "download_verified"
    assert result["validation"] == "header_and_length_only"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"", "invalid_header"),
        (b"<html>private login page</html>", "non_project_response"),
        ('{"LL":{"Code":"403","value":"secret"}}', "request_rejected"),
        ('{"LL":null}', "non_project_response"),
        ("[]", "non_project_response"),
        (b"PK\x03\x04", "invalid_zip"),
        (struct.pack("<IIII", 0xAABBCCEE, 2, 12, 0) + b"x", "invalid_length"),
        (struct.pack("<IIII", 0xAABBCCEE, 1, MAX_DECODED_BYTES + 1, 0), "size_limit"),
    ],
)
def test_rejects_invalid_or_unverified_response_without_leaking(payload, expected):
    result = classify(payload)
    assert result["result"] == expected
    assert "secret" not in str(result)
    assert "private" not in str(result)


def test_identity_selection_excludes_revoked_expired_and_explorer():
    family = dict(identity_id="one", miniserver_id="ms", expires_at=200, scope="loxone:read")
    document = {
        "families": {
            "active": family,
            "revoked": dict(family, identity_id="two", revoked=True),
            "expired": dict(family, identity_id="two", expires_at=50),
            "explorer": dict(family, identity_id="two", client_kind="tool_explorer"),
        }
    }
    assert select_family(document, 100) == ("active", family)
    document["families"]["other"] = dict(family, identity_id="two")
    assert select_family(document, 100) is None


def test_zip_validates_each_project_without_returning_names():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("private-one.LoxCC", "private-two.LoxCC"):
            archive.writestr(name, struct.pack("<IIII", 0xAABBCCEE, 1, 12, 0) + b"x")
    result = classify(buffer.getvalue())
    assert result["result"] == "download_verified"
    assert result["project_count"] == 2
    assert "private" not in str(result)


@pytest.mark.parametrize(
    "name,content,expected",
    [
        ("project.LoxCC", b"bad", "invalid_zip_project"),
        ("login.html", b"private", "zip_without_project"),
    ],
)
def test_zip_rejects_non_projects(name, content, expected):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, content)
    assert classify(buffer.getvalue())["result"] == expected


@pytest.mark.asyncio
async def test_http_encrypts_credentials_and_does_not_follow_redirects(monkeypatch):
    seen = []

    def encrypt(command, public_key):
        assert command == "dev/fsget/prog/sps.LoxCC?autht=secret&user=private"
        return "/encrypted-command"

    monkeypatch.setattr(
        diagnostic.CommandEncryptor,
        "generate",
        lambda: SimpleNamespace(encrypted_http_request=encrypt),
    )

    def respond(request):
        seen.append(request)
        assert "secret" not in str(request.url)
        assert "private" not in str(request.url)
        return httpx.Response(302, headers={"Location": "http://other.invalid/"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        diagnostic.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)),
    )
    result = await diagnostic.fetch_http(
        SimpleNamespace(endpoint=SimpleNamespace(secure=False, origin="http://test.invalid")),
        SimpleNamespace(_public_key="test-key"),
        SimpleNamespace(value="secret", username="private"),
    )
    assert result == {"result": "http_rejected", "status_code": 302}
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_confirmation_guard_prevents_token_access(monkeypatch, tmp_path):
    path = tmp_path / "existing"
    path.touch()
    settings = SimpleNamespace(store_path=path, loxone_store_path=path, install_key_path=path)
    monkeypatch.setattr(
        diagnostic.ServerSettings,
        "from_environment",
        lambda: SimpleNamespace(phase0_auth=settings),
    )
    family = dict(identity_id="one", miniserver_id="ms", expires_at=10**12, scope="loxone:read")
    store = SimpleNamespace(snapshot=lambda: {"families": {"active": family}})
    monkeypatch.setattr(diagnostic, "AtomicJsonAuthStore", lambda _: store)
    monkeypatch.setattr(
        diagnostic,
        "LoxoneTokenHealthStore",
        lambda _: SimpleNamespace(get=lambda _: SimpleNamespace(confirmation_required=True)),
    )

    def forbidden(*args):
        pytest.fail("Token access must not happen when confirmation is required")

    monkeypatch.setattr(diagnostic, "EncryptedLoxoneTokenStore", forbidden)
    assert await diagnostic.run() == {"result": "token_confirmation_required"}
