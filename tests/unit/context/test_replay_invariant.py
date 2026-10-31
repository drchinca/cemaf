"""Every state change on a Context must be recorded so replay reproduces it."""

from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch


def test_set_is_recorded_so_replay_reproduces_state() -> None:
    ctx = Context().apply(ContextPatch.set(path="a", value=1))
    ctx = ctx.set("b", 2)

    replayed = Context()
    for patch in ctx.patch_history:
        replayed = replayed.apply(patch)

    assert replayed.state_hash() == ctx.state_hash()


def test_merge_result_replays_to_its_own_state() -> None:
    left = Context().apply(ContextPatch.set(path="a", value=1))
    right = Context().apply(ContextPatch.set(path="b", value=2))

    merged = left.merge(right)

    replayed = Context()
    for patch in merged.patch_history:
        replayed = replayed.apply(patch)

    assert replayed.state_hash() == merged.state_hash()


def test_merge_and_append_do_not_share_nested_state_with_parent() -> None:
    base = Context().apply(ContextPatch.set(path="nested", value={"k": {"v": 1}}))

    child = base.deep_merge("nested", {"other": {"v": 2}}).append("items", {"v": 3})
    child.get("nested")["k"]["v"] = 99
    child.get("items")[0]["v"] = 99

    assert base.get("nested.k.v") == 1
    assert base.get("items") is None
    ctx = Context().apply(ContextPatch.set(path="nested", value={"k": 1}))

    ctx.to_dict()["nested"]["k"] = 99

    assert ctx.get("nested.k") == 1
