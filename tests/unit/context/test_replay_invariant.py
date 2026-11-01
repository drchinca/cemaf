"""Every state change on a Context must be recorded so replay reproduces it."""

import pytest

from cemaf.context.context import Context
from cemaf.context.merge import (
    DeepMergeStrategy,
    LastWriteWinsStrategy,
    MergeStrategy,
    RaiseOnConflictStrategy,
    ReducerMergeStrategy,
)
from cemaf.context.patch import ContextPatch, SecurityLevel


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


def test_parallel_join_result_replays_to_merged_state() -> None:
    base = Context().apply(ContextPatch.set(path="shared", value=0))
    left = base.set("left", 1)
    right = base.set("right", 2)

    joined = LastWriteWinsStrategy().merge(base=base, branches=[left, right]).context

    replayed = Context()
    for patch in joined.patch_history:
        replayed = replayed.apply(patch)

    assert replayed.state_hash() == joined.state_hash()
    assert joined.to_dict() == {"shared": 0, "left": 1, "right": 2}


def test_parallel_join_keeps_branch_classification_on_merge_patches() -> None:
    base = Context()
    secret = base.apply(
        ContextPatch.set(path="payroll.band", value="C", security_level=SecurityLevel.CONFIDENTIAL)
    )
    public = base.apply(ContextPatch.set(path="office", value="Lima", security_level=SecurityLevel.PUBLIC))

    joined = LastWriteWinsStrategy().merge(base=base, branches=[secret, public]).context
    levels = {p.path: p.security_level for p in joined.patch_history}

    assert levels["payroll"] == SecurityLevel.CONFIDENTIAL
    assert levels["office"] == SecurityLevel.PUBLIC


def test_parallel_join_keeps_dotted_top_level_keys_exact() -> None:
    base = Context(data={"flag": 1})
    branch = Context(data={"flag": True, "a.b": 2})

    joined = LastWriteWinsStrategy().merge(base=base, branches=[branch]).context

    assert joined.to_dict() == {"flag": True, "a.b": 2}
    assert joined.get("flag") is True


@pytest.mark.parametrize(
    "strategy",
    [
        LastWriteWinsStrategy(),
        RaiseOnConflictStrategy(),
        DeepMergeStrategy(),
        ReducerMergeStrategy(reducers={"total": sum}),
    ],
    ids=["last_write_wins", "raise_on_conflict", "deep_merge", "reducer"],
)
def test_every_merge_strategy_result_replays_to_its_state(strategy: MergeStrategy) -> None:
    base = Context().apply(ContextPatch.set(path="shared", value={"a": 1}))
    left = base.set("left", 1).set("total", 2)
    right = base.set("right", 2)

    joined = strategy.merge(base=base, branches=[left, right]).context

    replayed = Context()
    for patch in joined.patch_history:
        replayed = replayed.apply(patch)
    assert replayed.state_hash() == joined.state_hash()


@pytest.mark.parametrize(
    "strategy",
    [LastWriteWinsStrategy(), DeepMergeStrategy(), ReducerMergeStrategy()],
    ids=["last_write_wins", "deep_merge", "reducer"],
)
def test_branch_deletion_propagates_unless_another_branch_changed_the_key(strategy: MergeStrategy) -> None:
    base = Context().set("keep", 1).set("drop", 2).set("contested", 3)
    left = base.delete("drop").delete("contested")
    right = base.set("contested", 30).set("added", 4)

    joined = strategy.merge(base=base, branches=[left, right]).context

    assert joined.to_dict() == {"keep": 1, "contested": 30, "added": 4}
    replayed = Context()
    for patch in joined.patch_history:
        replayed = replayed.apply(patch)
    assert replayed.state_hash() == joined.state_hash()
