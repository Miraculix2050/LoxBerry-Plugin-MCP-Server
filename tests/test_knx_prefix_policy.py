"""Prefix activation is an explicit revision-bound Admin policy change."""

from dataclasses import replace

import pytest

from mcpserver.auth.store import AtomicJsonAuthStore
from mcpserver.config import PluginConfig
from mcpserver.knx.model import KnxError
from mcpserver.knx.read_admin import READ_POLICY, WRITE_POLICY, dispatch, policy_revision


def test_prefix_flag_changes_only_write_revision_and_legacy_payload_preserves_it(tmp_path):
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    before = PluginConfig.defaults()
    enabled = replace(before, loxberry_knx_prefix_write_enabled=True)
    target = "https://synthetic.example"
    assert policy_revision(before, target, READ_POLICY) == policy_revision(
        enabled, target, READ_POLICY
    )
    assert policy_revision(before, target, WRITE_POLICY) != policy_revision(
        enabled, target, WRITE_POLICY
    )
    saved = []
    result = dispatch(
        "knx_write_enable",
        {
            "target": target,
            "policy_revision": policy_revision(enabled, target, WRITE_POLICY),
            "enabled": False,
        },
        enabled,
        saved.append,
        auth,
        target,
        WRITE_POLICY,
    )
    assert saved[0].loxberry_knx_prefix_write_enabled and result["allow_prefixes"]
    with pytest.raises(KnxError, match="revision_conflict"):
        dispatch(
            "knx_write_enable",
            {
                "policy_revision": policy_revision(before, target, WRITE_POLICY),
                "enabled": True,
                "allow_prefixes": True,
            },
            enabled,
            saved.append,
            auth,
            target,
            WRITE_POLICY,
        )


@pytest.mark.parametrize("value", [1, "true", None, []])
def test_invalid_prefix_flag_is_not_saved(tmp_path, value):
    config = PluginConfig.defaults()
    saved = []
    auth = AtomicJsonAuthStore(tmp_path / "auth.json")
    with pytest.raises(KnxError, match="delegation_invalid"):
        dispatch(
            "knx_write_enable",
            {
                "policy_revision": policy_revision(config, "target", WRITE_POLICY),
                "enabled": True,
                "allow_prefixes": value,
            },
            config,
            saved.append,
            auth,
            "target",
            WRITE_POLICY,
        )
    assert saved == []


def test_read_policy_cannot_enable_prefix_writes(tmp_path):
    config = PluginConfig.defaults()
    with pytest.raises(KnxError, match="delegation_invalid"):
        dispatch(
            "knx_read_enable",
            {
                "policy_revision": policy_revision(config, "target"),
                "enabled": True,
                "allow_prefixes": True,
            },
            config,
            lambda _: pytest.fail("must not save"),
            AtomicJsonAuthStore(tmp_path / "auth.json"),
            "target",
        )
