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


def test_merge_keeps_other_history_so_replay_reproduces_state() -> None:
    left = Context().apply(ContextPatch.set(path="a", value=1))
    right = Context().apply(ContextPatch.set(path="b", value=2))

    merged = left.merge(right)

    replayed = Context()
    for patch in merged.patch_history:
        replayed = replayed.apply(patch)

    assert replayed.state_hash() == merged.state_hash()


def test_to_dict_cannot_mutate_context_state() -> None:
    ctx = Context().apply(ContextPatch.set(path="nested", value={"k": 1}))

    ctx.to_dict()["nested"]["k"] = 99

    assert ctx.get("nested.k") == 1
