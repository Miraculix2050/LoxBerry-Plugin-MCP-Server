from types import SimpleNamespace

import pytest

from tools import diagnose_loxcc_access as diagnostic
from tools.diagnose_loxcc_access import select_family


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
