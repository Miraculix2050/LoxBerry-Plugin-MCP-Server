from __future__ import annotations

from collections import OrderedDict

import pytest

from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Freshness


def test_cache_isolates_users_and_marks_disconnect_stale() -> None:
    cache = UserStateCache(clock=lambda: 123.0)
    cache.begin_connection("miniserver:user-a")
    cache.apply(
        "miniserver:user-a",
        [StateEvent(uuid="state", value=1.0)],
        allowed_uuids={"state"},
    )
    cache.begin_connection("miniserver:user-b")

    assert cache.get("miniserver:user-a", "state").freshness is Freshness.CURRENT
    assert cache.get("miniserver:user-b", "state").freshness is Freshness.UNKNOWN

    cache.disconnect("miniserver:user-a")

    assert cache.get("miniserver:user-a", "state").freshness is Freshness.STALE
    assert cache.get("miniserver:user-a", "missing").freshness is Freshness.UNAVAILABLE


def test_cache_evicts_oldest_state_at_limit() -> None:
    cache = UserStateCache(max_states_per_user=2)
    cache.begin_connection("subject")
    cache.apply(
        "subject",
        [
            StateEvent(uuid="one", value=1.0),
            StateEvent(uuid="two", value=2.0),
            StateEvent(uuid="three", value=3.0),
        ],
        allowed_uuids={"one", "two", "three"},
    )

    assert cache.get("subject", "one").freshness is Freshness.UNKNOWN
    assert cache.get("subject", "two").freshness is Freshness.CURRENT


def test_cache_drops_states_outside_the_filtered_structure() -> None:
    cache = UserStateCache()
    cache.begin_connection("subject")

    cache.apply(
        "subject",
        [
            StateEvent(uuid="allowed", value=1.0),
            StateEvent(uuid="denied", value=2.0),
        ],
        allowed_uuids={"allowed"},
    )

    assert cache.get("subject", "allowed").freshness is Freshness.CURRENT
    assert cache.get("subject", "denied").freshness is Freshness.UNKNOWN


def test_cache_purges_state_removed_from_the_filtered_structure() -> None:
    cache = UserStateCache()
    cache.begin_connection("subject")
    cache.apply(
        "subject",
        [
            StateEvent(uuid="still-allowed", value=1.0),
            StateEvent(uuid="revoked", value=2.0),
        ],
        allowed_uuids={"still-allowed", "revoked"},
    )

    cache.apply("subject", [], allowed_uuids={"still-allowed"})

    assert cache.get("subject", "still-allowed").freshness is Freshness.CURRENT
    assert cache.get("subject", "revoked").freshness is Freshness.UNKNOWN


def test_repeated_immutable_membership_checks_events_without_scanning_retained_states():
    cache = UserStateCache()
    allowed = frozenset({"allowed"})
    cache.apply("subject", [StateEvent("allowed", 1.0)], allowed_uuids=allowed)

    class NoScan(OrderedDict):
        def __iter__(self):
            raise AssertionError("unchanged membership scanned cached states")

    cache._values["subject"] = NoScan(cache._values["subject"])
    cache.apply(
        "subject", [StateEvent("denied", 2.0), StateEvent("allowed", 3.0)], allowed_uuids=allowed
    )
    assert cache.get("subject", "allowed").value == 3.0
    assert cache.get("subject", "denied").freshness is Freshness.UNKNOWN


def test_membership_changes_prune_immediately_and_mutable_edits_never_reuse_snapshot():
    cache = UserStateCache()
    original = frozenset({"one", "two"})
    cache.apply("subject", [StateEvent("one", 1.0), StateEvent("two", 2.0)], allowed_uuids=original)
    cache.apply("subject", [], allowed_uuids=frozenset({"one"}))
    assert cache.get("subject", "two").freshness is Freshness.UNKNOWN
    mutable = {"one", "three"}
    cache.apply("subject", [StateEvent("three", 3.0)], allowed_uuids=mutable)
    mutable.remove("three")
    cache.apply("subject", [], allowed_uuids=mutable)
    assert cache.get("subject", "three").freshness is Freshness.UNKNOWN
    cache.clear("subject")
    assert "subject" not in cache._allowed_snapshots


def test_membership_snapshot_is_reset_on_connection_lifecycle_and_isolated_by_subject():
    cache = UserStateCache()
    allowed = frozenset({"one"})
    cache.apply("first", [StateEvent("one", 1.0)], allowed_uuids=allowed)
    cache.apply("second", [], allowed_uuids=frozenset())
    assert cache.get("second", "one").freshness is Freshness.UNKNOWN
    cache.disconnect("first")
    assert "first" not in cache._allowed_snapshots
    assert cache.get("first", "one").freshness is Freshness.STALE
    cache.apply("first", [], allowed_uuids=allowed)
    cache.begin_connection("first")
    assert "first" not in cache._allowed_snapshots


def assert_accounted(cache):
    assert cache._total_bytes == sum(cache._sizes.values())
    assert cache._total_bytes == sum(cache._subject_bytes.values())
    assert cache._total_bytes == sum(cache._identity_bytes.values())
    assert all(size <= cache._identity_quota() for size in cache._identity_bytes.values())
    assert set(cache._sizes) == {
        key for values in cache._identity_entries.values() for key in values
    }
    assert set(cache._sizes) == {
        (subject, uuid) for subject, values in cache._values.items() for uuid in values
    }
    assert cache._total_bytes <= cache._max_total_bytes
    assert all(size <= cache._max_bytes_per_user for size in cache._subject_bytes.values())


def test_cache_byte_budget_evicts_oldest_ingested_without_read_promotion():
    cache = UserStateCache(max_bytes_per_user=2400)
    allowed = frozenset({"one", "two", "three"})
    for uuid in ("one", "two"):
        cache.apply("a", [StateEvent(uuid, "x" * 200)], allowed_uuids=allowed)
    assert cache.get("a", "one").freshness is Freshness.CURRENT
    cache.apply("a", [StateEvent("three", "x" * 200)], allowed_uuids=allowed)
    assert cache.get("a", "one").freshness is Freshness.UNKNOWN
    assert cache.get("a", "two").freshness is Freshness.CURRENT
    assert cache.get("a", "three").freshness is Freshness.CURRENT
    assert cache._byte_evictions == 1
    assert_accounted(cache)


@pytest.mark.parametrize("disconnected", [False, True])
def test_cache_global_budget_protects_distinct_identities_from_family_multiplication(disconnected):
    cache = UserStateCache(max_bytes_per_user=2400, max_total_bytes=6000)
    allowed = frozenset({"state"})
    cache.begin_connection("victim", identity_key=("server", "reader"))
    cache.apply("victim", [StateEvent("state", "v" * 200)], allowed_uuids=allowed)
    if disconnected:
        cache.disconnect("victim")
    for family in ("a", "b", "c", "d", "e"):
        cache.begin_connection(family, identity_key=("server", "other-reader"))
        cache.apply(family, [StateEvent("state", "x" * 200)], allowed_uuids=allowed)
    assert len(cache._identity_subjects) == 2
    assert cache.get("victim", "state").freshness is (
        Freshness.STALE if disconnected else Freshness.CURRENT
    )
    assert cache.get("victim", "state").value == "v" * 200
    assert sum(len(cache._values[family]) for family in ("a", "b", "c", "d", "e")) == 2
    assert_accounted(cache)


def test_actual_new_identities_receive_equal_capacity_and_cleanup_releases_it():
    cache = UserStateCache(max_bytes_per_user=4800, max_total_bytes=4800)
    allowed = frozenset({"one", "two", "three"})
    for family in ("a", "b", "c"):
        cache.begin_connection(family, identity_key=("server", family))
        cache.apply(family, [StateEvent(uuid, 1.0) for uuid in allowed], allowed_uuids=allowed)
    assert cache._identity_quota() == 1600
    assert all(len(values) == 1 for values in cache._values.values())
    assert all(value <= 1600 for value in cache._identity_bytes.values())
    assert_accounted(cache)
    cache.clear("b")
    cache.clear("c")
    assert cache._identity_quota() == 4800
    cache.apply("a", [StateEvent(uuid, 2.0) for uuid in allowed], allowed_uuids=allowed)
    assert len(cache._values["a"]) == 3
    assert_accounted(cache)


def test_identity_binding_uses_both_ids_and_never_shares_values_between_families():
    cache = UserStateCache()
    allowed = frozenset({"state"})
    for family, key in [("a", ("s1", "reader")), ("b", ("s1", "reader")), ("c", ("s2", "reader"))]:
        cache.begin_connection(family, identity_key=key)
    cache.apply("a", [StateEvent("state", 1.0)], allowed_uuids=allowed)
    assert len(cache._identity_subjects) == 2
    assert cache.get("b", "state").freshness is Freshness.UNKNOWN
    cache.begin_connection("a", identity_key=("s1", "different-reader"))
    assert cache.get("a", "state").freshness is Freshness.UNKNOWN
    assert_accounted(cache)


def test_oversized_replacement_discards_old_value_and_recovers_on_later_event():
    cache = UserStateCache(max_bytes_per_user=1200)
    allowed = frozenset({"state"})
    cache.apply("a", [StateEvent("state", 1.0)], allowed_uuids=allowed)
    cache.apply("a", [StateEvent("state", "x" * 2000)], allowed_uuids=allowed)
    assert cache.get("a", "state").freshness is Freshness.UNKNOWN
    assert cache._oversized_events == 1 and cache._total_bytes == 0
    cache.apply("a", [StateEvent("state", 2.0)], allowed_uuids=allowed)
    assert cache.get("a", "state").value == 2.0
    assert_accounted(cache)


def test_budget_accounting_survives_replacement_permission_pruning_and_lifecycle():
    cache = UserStateCache(max_states_per_user=2)
    allowed = {"one", "two", "three"}
    for uuid in allowed:
        cache.apply("a", [StateEvent(uuid, 1.0)], allowed_uuids=allowed)
        assert_accounted(cache)
    for uuid in allowed:
        cache.apply("a", [StateEvent(uuid, "larger")], allowed_uuids=allowed)
        assert_accounted(cache)
    allowed.clear()
    cache.apply("a", [], allowed_uuids=allowed)
    assert cache._total_bytes == 0 and not cache._sizes
    cache.apply("b", [StateEvent("one", 2.0)], allowed_uuids=frozenset({"one"}))
    size = cache._total_bytes
    cache.begin_connection("b")
    cache.disconnect("b")
    assert cache._total_bytes == size
    assert_accounted(cache)
    cache.clear_all()
    assert cache._total_bytes == 0 and not cache._sizes and not cache._subject_bytes
    assert not cache._values and not cache._available and not cache._allowed_snapshots
    assert not cache._subject_identity and not cache._identity_subjects
    assert not cache._identity_entries and not cache._identity_bytes


def test_structured_state_accounting_preserves_supported_decoder_trees():
    cache = UserStateCache()
    value = {"default_value": 1.0, "entries": [{"mode": 1, "value": 2.0}]}
    cache.apply("a", [StateEvent("state", value)], allowed_uuids={"state"})
    assert cache.get("a", "state").value == value
    assert cache._total_bytes > 512
    assert_accounted(cache)


@pytest.mark.parametrize("kind", ["cycle", "wide", "deep", "unsupported"])
def test_unaccountable_structures_fail_bounded_and_invalidate_old_state(kind):
    cache = UserStateCache()
    value = {}
    if kind == "cycle":
        value["self"] = value
    elif kind == "wide":
        value["entries"] = [None] * 70_000
    elif kind == "deep":
        current = value
        for _ in range(40):
            current["child"] = {}
            current = current["child"]
    else:
        value["value"] = object()
    cache.apply("a", [StateEvent("state", 1.0)], allowed_uuids={"state"})
    cache.apply("a", [StateEvent("state", value)], allowed_uuids={"state"})
    assert cache.get("a", "state").freshness is Freshness.UNKNOWN
    assert cache._oversized_events == 1
    assert_accounted(cache)


def test_unicode_values_use_retained_character_storage_not_utf8_wire_length():
    cache = UserStateCache(max_bytes_per_user=2000)
    cache.apply("a", [StateEvent("state", "\U0001f642" * 500)], allowed_uuids={"state"})
    assert cache.get("a", "state").freshness is Freshness.UNKNOWN
    assert cache._oversized_events == 1


@pytest.mark.parametrize("argument", ["max_bytes_per_user", "max_total_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_byte_budget_rejected(argument, value):
    with pytest.raises(ValueError, match="positive integers"):
        UserStateCache(**{argument: value})
