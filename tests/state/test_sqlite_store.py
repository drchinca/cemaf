"""Unit tests for SqliteFsmStore — protocol conformance, round-trip, locking."""

from __future__ import annotations

from pathlib import Path

import pytest

from cemaf.core.utils import utc_now
from cemaf.state import (
    FsmStore,
    SqliteFsmStore,
    VersionConflict,
    create_fsm_store,
)
from cemaf.state.transitions import FsmState, StateTransition


def _make_state(
    *,
    fsm_id: str = "ORD-1",
    kind: str = "order",
    current_state: str = "new",
    version: int = 0,
    history: list[StateTransition] | None = None,
) -> FsmState:
    return FsmState(
        fsm_id=fsm_id,
        fsm_kind=kind,
        current_state=current_state,
        history=history or [],
        metadata={"source": "unit-test"},
        version=version,
        updated_at=utc_now(),
    )


def _make_transition(*, from_state: str = "new", to_state: str = "paid") -> StateTransition:
    return StateTransition(
        from_state=from_state,
        to_state=to_state,
        event="pay",
        actor="cashier",
        actor_kind="human",
        triggered_at=utc_now(),
        correlation_id="run_test",
        metadata={"payment_token": "tok_1"},
    )


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_fsm.db")


def test_satisfies_fsm_store_protocol(db_path: str) -> None:
    """SqliteFsmStore is a structural FsmStore."""
    assert isinstance(SqliteFsmStore(db_path=db_path), FsmStore)


async def test_load_missing_returns_none(db_path: str) -> None:
    async with SqliteFsmStore(db_path=db_path) as store:
        assert await store.load(fsm_id="missing", kind="order") is None


async def test_save_load_roundtrip_preserves_history(db_path: str) -> None:
    """A saved record round-trips with history, metadata, and version intact."""
    async with SqliteFsmStore(db_path=db_path) as store:
        state = _make_state(current_state="paid", version=1, history=[_make_transition()])
        await store.save(state=state, expected_version=0)

        loaded = await store.load(fsm_id="ORD-1", kind="order")

        assert loaded is not None
        assert loaded.current_state == "paid"
        assert loaded.version == 1
        assert loaded.metadata == {"source": "unit-test"}
        assert len(loaded.history) == 1
        assert loaded.history[0].event == "pay"
        assert loaded.history[0].metadata == {"payment_token": "tok_1"}


async def test_save_wrong_expected_version_raises(db_path: str) -> None:
    """Optimistic locking: stale expected_version raises VersionConflict."""
    async with SqliteFsmStore(db_path=db_path) as store:
        await store.save(state=_make_state(version=0), expected_version=0)

        with pytest.raises(VersionConflict):
            await store.save(state=_make_state(version=3), expected_version=2)


async def test_missing_row_counts_as_version_zero(db_path: str) -> None:
    """Same semantics as InMemoryFsmStore: absent record has version 0."""
    async with SqliteFsmStore(db_path=db_path) as store:
        with pytest.raises(VersionConflict):
            await store.save(state=_make_state(version=2), expected_version=1)


async def test_list_filters_by_kind_and_current_state(db_path: str) -> None:
    async with SqliteFsmStore(db_path=db_path) as store:
        await store.save(state=_make_state(fsm_id="A", current_state="new"), expected_version=0)
        await store.save(state=_make_state(fsm_id="B", current_state="paid"), expected_version=0)
        await store.save(
            state=_make_state(fsm_id="C", kind="invoice", current_state="new"),
            expected_version=0,
        )

        orders = await store.list(kind="order")
        assert {s.fsm_id for s in orders} == {"A", "B"}

        paid = await store.list(kind="order", current_state="paid")
        assert [s.fsm_id for s in paid] == ["B"]

        assert await store.list(kind="unknown") == []


async def test_persistence_across_store_instances(db_path: str) -> None:
    """A second store instance on the same path sees the first one's writes."""
    async with SqliteFsmStore(db_path=db_path) as first:
        await first.save(state=_make_state(current_state="shipped", version=2), expected_version=0)

    async with SqliteFsmStore(db_path=db_path) as second:
        loaded = await second.load(fsm_id="ORD-1", kind="order")
        assert loaded is not None
        assert loaded.current_state == "shipped"
        assert loaded.version == 2


async def test_factory_creates_sqlite_backend(db_path: str) -> None:
    """create_fsm_store(backend="sqlite") builds a working SqliteFsmStore."""
    store = create_fsm_store(backend="sqlite", db_path=db_path)
    assert isinstance(store, SqliteFsmStore)
    try:
        await store.save(state=_make_state(), expected_version=0)
        assert await store.load(fsm_id="ORD-1", kind="order") is not None
    finally:
        await store.close()
