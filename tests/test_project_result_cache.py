import pytest

from mcpserver.loxone.project.result_cache import ProjectResultCache


def test_result_eviction_and_expiry_invalidate_private_cursor_generations():
    cache = ProjectResultCache[list[int]](max_entries=2, max_bytes=10, max_leases=2)
    cache.put("a", [1], expires=5, size=5)
    scope = cache.cursor_scope("family", "a", continuation=False)
    cache.bind("family", "a", scope, expires=5)
    cache.put("b", [2], expires=6, size=5)
    cache.put("c", [3], expires=7, size=5)
    assert cache.cache_bytes == 10
    with pytest.raises(ValueError, match="expired"):
        cache.cursor_scope("family", "a", continuation=True)
    cache.put("a", [1], expires=8, size=5)
    renewed = cache.cursor_scope("family", "a", continuation=False)
    assert renewed != scope
    cache.bind("family", "a", renewed, expires=8)
    cache.prune(8)
    assert cache.cache_bytes == 0
    assert not cache.entries and not cache.leases
    with pytest.raises(ValueError, match="expired"):
        cache.cursor_scope("family", "a", continuation=True)


def test_family_lease_bound_does_not_evict_shared_result():
    cache = ProjectResultCache[list[int]](max_entries=1, max_bytes=10, max_leases=2)
    cache.put("result", [1], expires=10, size=5)
    for family in ("first", "second", "third"):
        scope = cache.cursor_scope(family, "result", continuation=False)
        cache.bind(family, "result", scope, expires=10)
    assert list(cache.leases) == ["second", "third"]
    assert cache.get("result") is not None
    with pytest.raises(ValueError, match="expired"):
        cache.cursor_scope("first", "result", continuation=True)
    cache.put("result", [2], expires=10, size=6)
    assert cache.cache_bytes == 6
    cache.bind("missing", "evicted", "scope", expires=10)
    assert "missing" not in cache.leases
    with pytest.raises(ValueError, match="bound"):
        cache.put("oversize", [], expires=10, size=11)
    assert cache.cache_bytes == 6


def test_authorized_borrowed_hit_is_restored_without_extending_expiry():
    cache = ProjectResultCache[list[int]](max_entries=1, max_bytes=10, max_leases=2)
    cache.put("result", [1], expires=5, size=5)
    borrowed = cache.get("result")
    assert borrowed is not None
    cache.put("concurrent", [2], expires=10, size=5)
    assert cache.get("result") is None
    cache.retain("result", borrowed, now=4)
    assert cache.get("result") == borrowed
    assert list(cache.entries) == ["result"] and cache.cache_bytes == 5
    with pytest.raises(ValueError, match="expired"):
        cache.retain("result", borrowed, now=5)
