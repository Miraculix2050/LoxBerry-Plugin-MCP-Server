"""Prefix effects share one configuration save with their bounded receipt."""

from dataclasses import replace

import pytest

from mcpserver.config import ConfigError, PluginConfig
from mcpserver.knx import prefix_apply as module
from mcpserver.knx.catalog import labels_revision, manual_labels, prefix_projection
from mcpserver.knx.model import KnxError
from mcpserver.knx.prefix_receipts import LIMIT, TTL, PrefixReceipt, parse_receipts, receipt_key
from mcpserver.knx.store import KnxStore
from mcpserver.loxone.project.taxonomy import parse_taxonomy

TARGET = "http://192.168.99.1"
OWNER = "a" * 64
REQUEST = "b" * 32
DIGEST = "c" * 64


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(module.time, "time", lambda: 100)
    store = KnxStore(tmp_path / "metadata.sqlite3")
    store.put(
        TARGET,
        0,
        {"address": "0/0/1", "address_format": "three_level", "fields": {"name": "Untouched"}},
    )
    entries = parse_taxonomy(
        [
            {"address_format": "three_level", "prefix": "0/0", "label": "Old"},
            {"address_format": "two_level", "prefix": "0/0", "label": "Other style"},
        ]
    )
    config = replace(
        PluginConfig.defaults(),
        knx_address_taxonomy_endpoint=TARGET,
        knx_address_taxonomy=entries,
        knx_taxonomy_targets=(("http://192.168.99.2", entries),),
    )
    return store, config


def changes():
    return [
        {
            "kind": "prefix",
            "destination": "local_metadata",
            "field": "label",
            "decision": "accepted",
            "address_format": "three_level",
            "prefix": "0/0",
            "operation": "set",
            "value": "Updated",
        }
    ]


def apply(setup, selected=None, **kwargs):
    store, config = setup
    saved = []
    result = module.apply_prefixes(
        store,
        config,
        OWNER,
        TARGET,
        REQUEST,
        DIGEST,
        1,
        labels_revision(config, TARGET),
        changes() if selected is None else selected,
        expires_at=kwargs.pop("expires_at", 200),
        save=kwargs.pop("save", saved.append),
        authorize_effect=kwargs.pop("authorize_effect", lambda: None),
        **kwargs,
    )
    return result, saved


def test_atomic_config_receipt_preserves_catalog_other_style_and_inactive_bank(setup):
    store, before = setup
    catalog = store.page(TARGET)
    result, saved = apply(setup)
    assert len(saved) == 1
    after = saved[0]
    assert store.page(TARGET) == catalog
    assert result["catalog_revision"] == 1 and result["changed_prefixes"] == 1
    assert result["manual_revision"] == labels_revision(after, TARGET)
    assert result["manual_revision"] != labels_revision(before, TARGET)
    assert manual_labels(after, TARGET) == [
        {"address_format": "three_level", "prefix": "0/0", "label": "Updated"},
        {"address_format": "two_level", "prefix": "0/0", "label": "Other style"},
    ]
    assert dict(after.knx_taxonomy_targets)["http://192.168.99.2"] == before.knx_address_taxonomy
    assert module.receipt(after, OWNER, TARGET, REQUEST, DIGEST, 101) == result
    assert module.receipt(after, "d" * 64, TARGET, REQUEST, DIGEST, 101) is None
    assert module.receipt(after, OWNER, "other", REQUEST, DIGEST, 101) is None
    with pytest.raises(KnxError, match="request_conflict"):
        module.receipt(after, OWNER, TARGET, REQUEST, "d" * 64, 101)
    with pytest.raises(KnxError, match="receipt_expired"):
        module.receipt(after, OWNER, TARGET, REQUEST, DIGEST, 100 + TTL)
    assert "Updated" not in str(after.knx_prefix_apply_receipts[0].document())
    assert PluginConfig.from_document(after.to_document()) == after


def test_remove_reveals_imported_label_without_altering_import(setup):
    store, _ = setup
    with store.connection() as db:
        db.execute(
            "INSERT INTO import_groups VALUES (?, ?, ?, ?, ?, 1)",
            (TARGET, "three_level", "0/0", '{"name":"ETS label"}', "{}"),
        )
        db.commit()
    selected = changes()
    selected[0].update(operation="remove_override")
    selected[0].pop("value")
    _, saved = apply(setup, selected)
    projection = prefix_projection(
        [{"address_format": "three_level", "prefix": "0/0", "label": "ETS label"}],
        manual_labels(saved[0], TARGET),
    )
    assert projection["three_level:0/0"]["sources"] == {"imported": "ETS label"}
    with store.connection() as db:
        assert db.execute("SELECT fields,selected FROM import_groups").fetchone() == (
            '{"name":"ETS label"}',
            1,
        )


@pytest.mark.parametrize(
    "damage",
    [
        {"kind": "address"},
        {"decision": "proposed"},
        {"field": "name"},
        {"prefix": "00/0"},
        {"value": "x" * 81},
        {"operation": "remove_override"},
        {"prefix": ["0"]},
        {"address_format": "free"},
    ],
)
def test_invalid_selection_has_no_effect_or_receipt(setup, damage):
    selected = changes()
    selected[0].update(damage)
    saved = []
    with pytest.raises(KnxError):
        apply(setup, selected, save=saved.append)
    assert saved == []


def test_authorization_revocation_and_deadline_after_wait_prevent_save(setup, monkeypatch):
    saved = []

    def denied():
        raise PermissionError("revoked")

    with pytest.raises(PermissionError):
        apply(setup, save=saved.append, authorize_effect=denied)

    def expired():
        monkeypatch.setattr(module.time, "time", lambda: 200)

    with pytest.raises(KnxError, match="draft_unavailable"):
        apply(setup, save=saved.append, authorize_effect=expired)
    assert saved == []


def test_save_failure_does_not_mutate_input_or_catalog(setup):
    store, before = setup
    snapshot = store.page(TARGET)

    def fail(_):
        raise OSError("synthetic")

    with pytest.raises(OSError):
        apply(setup, save=fail)
    assert not before.knx_prefix_apply_receipts
    assert store.page(TARGET) == snapshot


def test_fractional_deadline_after_authorization_does_not_allow_expired_effect(setup, monkeypatch):
    saved = []

    def after_deadline():
        monkeypatch.setattr(module.time, "time", lambda: 200.75)

    with pytest.raises(KnxError, match="draft_unavailable"):
        apply(setup, save=saved.append, authorize_effect=after_deadline, expires_at=200.5)
    assert saved == []


def test_unexpired_receipt_capacity_blocks_without_eviction(setup):
    store, config = setup
    receipts = tuple(
        PrefixReceipt(
            receipt_key(OWNER, TARGET, str(i)),
            DIGEST,
            labels_revision(config, TARGET),
            1,
            1,
            1,
            150,
        )
        for i in range(LIMIT)
    )
    config = replace(config, knx_prefix_apply_receipts=receipts)
    saved = []
    with pytest.raises(KnxError, match="receipt_limit"):
        apply((store, config), save=saved.append)
    assert saved == []
    expired = replace(
        config, knx_prefix_apply_receipts=tuple(replace(row, expires_at=100) for row in receipts)
    )
    _, saved = apply((store, expired))
    assert len(saved[0].knx_prefix_apply_receipts) == 1


def test_noop_keeps_manual_revision_but_records_confirmed_operation(setup):
    selected = changes()
    selected[0]["value"] = "Old"
    result, saved = apply(setup, selected)
    assert result["changed_prefixes"] == 0
    assert result["manual_revision"] == labels_revision(setup[1], TARGET)
    assert len(saved[0].knx_prefix_apply_receipts) == 1


@pytest.mark.parametrize(
    "damage",
    [
        {"selected_changes": True},
        {"key": "bad"},
        {"changed_prefixes": 2},
        {"private_value": "hidden"},
    ],
)
def test_receipt_codec_fails_closed(damage):
    row = PrefixReceipt("a" * 64, "b" * 64, "c" * 64, 0, 1, 1, 200).document()
    row.update(damage)
    with pytest.raises(ValueError):
        parse_receipts([row])
    with pytest.raises(ConfigError):
        PluginConfig.from_document({"schema_version": 12, "knx_prefix_apply_receipts": [row]})


def test_legacy_config_defaults_to_no_prefix_permission_and_empty_receipts():
    config = PluginConfig.from_document({"schema_version": 11})
    assert not config.loxberry_knx_prefix_write_enabled
    assert config.knx_prefix_apply_receipts == ()
    assert config.to_document()["schema_version"] == 12


def test_compact_receipts_retain_exact_semantics_and_read_legacy_objects():
    row = PrefixReceipt("a" * 64, "b" * 64, "c" * 64, 1, 1, 1, 200)
    assert parse_receipts([row.config_record()]) == parse_receipts([row.document()]) == (row,)
    config = PluginConfig.from_document(
        {"schema_version": 12, "knx_prefix_apply_receipts": [row.document()]}
    )
    assert config.to_document()["knx_prefix_apply_receipts"] == [row.config_record()]
    assert PluginConfig.from_document(config.to_document()).knx_prefix_apply_receipts == (row,)
    assert row.result()["manual_revision"] == "c" * 64


@pytest.mark.parametrize("column,value", [(0, "short"), (1, True), (3, True), (4, 0), (5, 2)])
def test_compact_receipt_columns_fail_closed(column, value):
    record = PrefixReceipt("a" * 64, "b" * 64, "c" * 64, 1, 1, 1, 200).config_record()
    record[column] = value
    with pytest.raises(ValueError):
        parse_receipts([record])


@pytest.mark.parametrize("size", [0, 6, 8])
def test_compact_receipt_rejects_missing_or_additional_columns(size):
    with pytest.raises(ValueError):
        parse_receipts([["a"] * size])


def test_imported_and_manual_union_limit_prevents_partial_overflow(setup):
    store, config = setup
    with store.connection() as db:
        for number in range(127):
            db.execute(
                "INSERT INTO import_groups VALUES (?, ?, ?, ?, ?, 1)",
                (TARGET, "three_level", f"0/1/{number}", '{"name":"Imported"}', "{}"),
            )
        db.commit()
    saved = []
    with pytest.raises(KnxError, match="label_limit"):
        apply((store, config), save=saved.append)
    assert saved == []


def test_corrupt_selected_import_is_storage_failure_and_never_empty_inventory(setup):
    store, _ = setup
    with store.connection() as db:
        db.execute(
            "INSERT INTO import_groups VALUES (?, ?, ?, ?, ?, 1)",
            (TARGET, "three_level", "0/0", "{}", "{}"),
        )
        db.commit()
    saved = []
    with pytest.raises(KnxError, match="storage_failed"):
        apply(setup, save=saved.append)
    assert saved == []
