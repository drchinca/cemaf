"""
Tests for Context state hashing and timeline navigation.
"""

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource


def test_context_state_hash_deterministic():
    """Test that state_hash is deterministic for the same data."""
    ctx1 = Context(data={"a": 1, "b": [1, 2, 3]})
    ctx2 = Context(data={"a": 1, "b": [1, 2, 3]})

    assert ctx1.state_hash() == ctx2.state_hash()
    assert len(ctx1.state_hash()) == 64  # SHA256 hex length


def test_context_state_hash_changes_with_data():
    """Test that state_hash changes when data changes."""
    ctx1 = Context(data={"a": 1})
    ctx2 = Context(data={"a": 2})

    assert ctx1.state_hash() != ctx2.state_hash()


def test_context_state_hash_with_patches():
    """Test that state_hash includes patch history for provenance-aware caching."""
    patch = ContextPatch(
        path="user", operation=PatchOperation.SET, value="alice", source=PatchSource.USER, reason="init"
    )

    ctx1 = Context(data={"user": "alice"})
    ctx2 = Context(data={"user": "alice"}).apply(patch)

    # Even though data is same, ctx2 has a patch history (provenance)
    # For semantic caching we might want them same, but for exact state hashing
    # including provenance is safer for "instant regeneration".
    assert ctx1.state_hash() != ctx2.state_hash()


def test_context_timeline_navigation():
    """Test get_timeline and rollback_to."""
    ctx = Context()
    p1 = ContextPatch(path="a", operation=PatchOperation.SET, value=1, source=PatchSource.USER)
    p2 = ContextPatch(path="b", operation=PatchOperation.SET, value=2, source=PatchSource.USER)

    ctx1 = ctx.apply(p1)
    ctx2 = ctx1.apply(p2)

    timeline = ctx2.get_timeline()
    assert len(timeline) == 2
    assert timeline[0].id == p1.id
    assert timeline[1].id == p2.id

    # Rollback to p1
    ctx_rolled = ctx2.rollback_to(p1.id)
    assert ctx_rolled.get("a") == 1
    assert ctx_rolled.get("b") is None
    assert len(ctx_rolled.get_timeline()) == 1

    # Rollback to beginning (empty string or None)
    ctx_init = ctx2.rollback_to(None)
    assert ctx_init.data == {}
    assert len(ctx_init.get_timeline()) == 0
