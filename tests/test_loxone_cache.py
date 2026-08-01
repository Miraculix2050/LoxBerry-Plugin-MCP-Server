from __future__ import annotations

from mcpserver.loxone.cache import UserStateCache
from mcpserver.loxone.events import StateEvent
from mcpserver.loxone.models import Freshness


def test_cache_isolates_users_and_marks_disconnect_stale() -> None:
    cache = UserStateCache(clock=lambda: 123.0)
    cache.begin_connection("miniserver:user-a")
    cache.apply("miniserver:user-a", [StateEvent(uuid="state", value=1.0)])
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
    )

    assert cache.get("subject", "one").freshness is Freshness.UNKNOWN
    assert cache.get("subject", "two").freshness is Freshness.CURRENT
