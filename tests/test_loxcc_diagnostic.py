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
    assert select_family(document, 100, use_tool_explorer=True) == (
        "explorer",
        document["families"]["explorer"],
    )
    document["families"]["other"] = dict(family, identity_id="two")
    assert select_family(document, 100) is None


def test_cli_uses_documented_non_explorer_default(monkeypatch, capsys):
    async def fake_run(*, use_tool_explorer: bool = False):
        assert use_tool_explorer is False
        return {"result": "pipeline_verified"}

    monkeypatch.setattr(diagnostic, "run", fake_run)
    monkeypatch.setattr(diagnostic.logging, "disable", lambda _level: None)
    assert diagnostic.main([]) == 0
    assert "pipeline_verified" in capsys.readouterr().out


def test_cli_can_explicitly_select_tool_explorer(monkeypatch, capsys):
    async def fake_run(*, use_tool_explorer: bool = False):
        assert use_tool_explorer is True
        return {"result": "pipeline_verified"}

    monkeypatch.setattr(diagnostic, "run", fake_run)
    monkeypatch.setattr(diagnostic.logging, "disable", lambda _level: None)
    assert diagnostic.main(["--tool-explorer"]) == 0
    assert "pipeline_verified" in capsys.readouterr().out


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
