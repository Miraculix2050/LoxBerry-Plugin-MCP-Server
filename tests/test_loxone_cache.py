from __future__ import annotations

from collections import OrderedDict

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
