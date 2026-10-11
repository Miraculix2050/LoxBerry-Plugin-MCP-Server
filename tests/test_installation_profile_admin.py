from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from mcpserver.admin_errors import AdminError
from mcpserver.config import AtomicConfigStore, PluginConfig
from mcpserver.installation_profile_admin import dispatch_profile
from mcpserver.loxone.models import Control

CONTROL = "00000001-0000-0000-0000000000000001"
STATE = "00000002-0000-0000-0000000000000002"
TARGET = hashlib.sha256(b"synthetic").hexdigest()


def test_profile_dom_confirmation_and_revision_flows():
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run(
        [node, "--test", "tests/js/profile-behavior.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def setup(tmp_path: Path, monkeypatch):
    config = AtomicConfigStore(tmp_path / "config.json")
    config.save(PluginConfig(loxone_endpoint="http://192.168.1.10"))
    monkeypatch.setenv("LBPDATA", str(tmp_path))
    visible = {
        CONTROL: Control(
            CONTROL, "Synthetic", "InfoOnlyAnalog", None, None, None, (("value", STATE),)
        )
    }
    calls = []

    def context(_config):
        calls.append(True)
        return TARGET, visible

    monkeypatch.setattr("mcpserver.installation_profile_admin._context", context)
    return config, visible, calls


def payload(revision=0):
    return {
        "installation": TARGET,
        "revision": revision,
        "confirm": True,
        "binding": {
            "binding_id": "temperature",
            "role": "actual_temperature",
            "control_uuid": CONTROL,
            "source_kind": "state",
            "state_uuid": STATE,
            "confirmed": True,
        },
    }


def test_admin_profile_confirmation_revision_and_visibility(tmp_path, monkeypatch):
    config, visible, calls = setup(tmp_path, monkeypatch)
    result = dispatch_profile("profile_put", payload(), config)
    assert result["bindings"][0]["status"] == "confirmed"
    assert len(calls) == 1
    with pytest.raises(AdminError) as error:
        dispatch_profile("profile_put", payload(), config)
    assert error.value.code == "profile_revision_conflict"
    visible.clear()
    page = dispatch_profile("profile_page", {}, config)
    assert page["bindings"] == [] and page["sources"] == []
    assert CONTROL not in json.dumps(page)


@pytest.mark.parametrize(
    "change",
    [{"confirm": False}, {"revision": True}, {"installation": "wrong"}, {"extra": "forbidden"}],
)
def test_admin_write_rejects_unconfirmed_or_stale_requests(tmp_path, monkeypatch, change):
    config, _visible, _calls = setup(tmp_path, monkeypatch)
    with pytest.raises(AdminError):
        dispatch_profile("profile_put", {**payload(), **change}, config)
    assert not (tmp_path / "installation-profile.json").exists()


def test_cgi_and_ui_use_same_origin_and_safe_text_and_localized_keys():
    root = Path(__file__).resolve().parents[1]
    cgi = (root / "webfrontend/htmlauth/profile.cgi").read_text()
    script = (root / "webfrontend/htmlauth/profile.js").read_text()
    template = (root / "templates/profile.html").read_text()
    assert "same_origin_post()" in cgi
    assert (
        r"\A(?:profile_page|profile_put|profile_delete|profile_permissions|profile_permission_enable|profile_permission_allow|profile_permission_revoke)\z"
        in cgi
    )
    assert "alarm 60" in cgi and "MCPSERVER_EVENT_HISTORY_STORE" in cgi
    assert '$ENV{MCPSERVER_AUTH_STORE} = "$lbpdatadir/auth/sessions.json";' in cgi
    assert "innerHTML" not in script and ".textContent" in script
    assert 'get("confirmed").checked = false' in script
    assert 'id="profile-fields"' in template and "disabled" in template
    import re

    required = set(re.findall(r"PROFILE\.([A-Z_]+)", template))
    for language in ("de", "en"):
        text = (root / f"templates/lang/language_{language}.ini").read_text()
        section = text.split("[PROFILE]", 1)[1].split("\n[", 1)[0]
        assert required <= set(re.findall(r"^([A-Z_]+)=", section, re.M))
