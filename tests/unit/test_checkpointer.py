"""
Tests for checkpointing.

Verifies checkpoint save/load/resume functionality.
"""

import pytest

from cemaf.core.enums import RunStatus
from cemaf.core.types import NodeID, RunID
from cemaf.orchestration.checkpointer import (
    DAGCheckpoint,
    InMemoryCheckpointer,
)


class TestDAGCheckpoint:
    """Tests for DAGCheckpoint."""

    def test_can_resume_running(self):
        """RUNNING checkpoint can be resumed."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.RUNNING,
        )
        assert checkpoint.can_resume()

    def test_can_resume_pending(self):
        """PENDING checkpoint can be resumed."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.PENDING,
        )
        assert checkpoint.can_resume()

    def test_can_resume_failed(self):
        """FAILED checkpoint can be resumed."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.FAILED,
        )
        assert checkpoint.can_resume()

    def test_cannot_resume_completed(self):
        """COMPLETED checkpoint cannot be resumed."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.COMPLETED,
        )
        assert not checkpoint.can_resume()

    def test_completed_nodes_tracking(self):
        """Checkpoint tracks completed nodes."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.RUNNING,
            completed_nodes=(NodeID("node1"), NodeID("node2")),
            pending_nodes=(NodeID("node3"),),
        )
        assert len(checkpoint.completed_nodes) == 2
        assert len(checkpoint.pending_nodes) == 1


class TestInMemoryCheckpointer:
    """Tests for InMemoryCheckpointer."""

    @pytest.fixture
    def checkpointer(self) -> InMemoryCheckpointer:
        return InMemoryCheckpointer()

    @pytest.mark.asyncio
    async def test_save_and_load(self, checkpointer: InMemoryCheckpointer):
        """Can save and load checkpoint."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.RUNNING,
        )

        await checkpointer.save(checkpoint)
        loaded = await checkpointer.load(RunID("test_run"))

        assert loaded is not None
        assert loaded.run_id == checkpoint.run_id
        assert loaded.dag_name == checkpoint.dag_name

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, checkpointer: InMemoryCheckpointer):
        """Loading nonexistent checkpoint returns None."""
        loaded = await checkpointer.load(RunID("nonexistent"))
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete(self, checkpointer: InMemoryCheckpointer):
        """Can delete checkpoint."""
        checkpoint = DAGCheckpoint(
            run_id=RunID("test_run"),
            dag_name="test_dag",
            status=RunStatus.RUNNING,
        )

        await checkpointer.save(checkpoint)
        result = await checkpointer.delete(RunID("test_run"))

        assert result is True
        assert await checkpointer.load(RunID("test_run")) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, checkpointer: InMemoryCheckpointer):
        """Deleting nonexistent checkpoint returns False."""
        result = await checkpointer.delete(RunID("nonexistent"))
        assert result is False

    @pytest.mark.asyncio
    async def test_clear(self, checkpointer: InMemoryCheckpointer):
        """Can clear all checkpoints."""
        await checkpointer.save(
            DAGCheckpoint(
                run_id=RunID("run1"),
                dag_name="dag1",
                status=RunStatus.RUNNING,
            )
        )
        await checkpointer.save(
            DAGCheckpoint(
                run_id=RunID("run2"),
                dag_name="dag2",
                status=RunStatus.COMPLETED,
            )
        )

        await checkpointer.clear()

        assert await checkpointer.load(RunID("run1")) is None
        assert await checkpointer.load(RunID("run2")) is None
