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


def test_merge_records_other_values_so_replay_reproduces_state() -> None:
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


def test_mutators_survive_checkpoint_and_replay_each_intermediate_state() -> None:
    ctx = Context().set("project", {"status": "draft", "tags": []})
    snapshots = [ctx]
    ctx = ctx.append("project.tags", "reviewed")
    snapshots.append(ctx)
    ctx = ctx.deep_merge("project", {"status": "approved", "details": {"revision": 2}})
    snapshots.append(ctx)
    ctx = ctx.delete("project.status")
    snapshots.append(ctx)
    ctx = ctx.merge(Context(data={"published": True}))
    snapshots.append(ctx)

    restored = Context.from_checkpoint_dict(ctx.to_checkpoint_dict())
    for snapshot in snapshots:
        assert restored.rollback_to(snapshot.patch_history[-1].id).to_dict() == snapshot.to_dict()
    assert restored.to_dict() == {
        "project": {"tags": ["reviewed"], "details": {"revision": 2}},
        "published": True,
    }
