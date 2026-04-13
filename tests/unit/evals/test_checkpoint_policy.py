"""Tests for checkpoint policies — strategy-based checkpoint placement."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cemaf.core.enums import NodeType
from cemaf.evals.checkpoint_policy import (
    AfterRiskPolicy,
    CheckpointPolicy,
    EveryNNodesPolicy,
    LLMCheckpointPolicy,
    MarkedNodesPolicy,
)
from cemaf.orchestration.dag import DAG, Edge, Node


def _build_dag() -> DAG:
    """Build a 5-node DAG for testing."""
    dag = DAG(name="test", description="test dag")
    dag = dag.add_node(node=Node.agent(id="a1", name="Agent 1", agent_id="t1", output_key="o1"))
    dag = dag.add_node(node=Node.agent(id="a2", name="Agent 2", agent_id="t2", output_key="o2"))
    dag = dag.add_node(node=Node.agent(id="a3", name="Agent 3", agent_id="t3", output_key="o3"))
    dag = dag.add_node(node=Node.tool(id="t4", name="Tool 4", tool_id="tool1", output_key="o4"))
    dag = dag.add_node(node=Node.agent(id="a5", name="Agent 5", agent_id="t5", output_key="o5"))
    dag = dag.add_edge(edge=Edge(source="a1", target="a2"))
    dag = dag.add_edge(edge=Edge(source="a2", target="a3"))
    dag = dag.add_edge(edge=Edge(source="a3", target="t4"))
    dag = dag.add_edge(edge=Edge(source="t4", target="a5"))
    return dag


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestCheckpointPolicyProtocol:
    def test_marked_nodes_satisfies_protocol(self) -> None:
        assert isinstance(MarkedNodesPolicy(node_ids=set()), CheckpointPolicy)

    def test_every_n_satisfies_protocol(self) -> None:
        assert isinstance(EveryNNodesPolicy(n=3), CheckpointPolicy)

    def test_after_risk_satisfies_protocol(self) -> None:
        assert isinstance(AfterRiskPolicy(), CheckpointPolicy)

    def test_llm_policy_satisfies_protocol(self) -> None:
        assert isinstance(LLMCheckpointPolicy(llm_client=None), CheckpointPolicy)


# ---------------------------------------------------------------------------
# Node.with_checkpoint() toggle
# ---------------------------------------------------------------------------


class TestNodeCheckpointToggle:
    def test_default_checkpoint_is_false(self) -> None:
        node = Node.agent(id="a1", name="Agent", agent_id="test")
        assert node.checkpoint_enabled is False

    def test_with_checkpoint_enables(self) -> None:
        node = Node.agent(id="a1", name="Agent", agent_id="test")
        marked = node.with_checkpoint(enabled=True)
        assert marked.checkpoint_enabled is True
        assert str(marked.id) == "a1"
        assert marked.type == NodeType.AGENT

    def test_with_checkpoint_disables(self) -> None:
        node = Node.agent(id="a1", name="Agent", agent_id="test")
        marked = node.with_checkpoint(enabled=True)
        unmarked = marked.with_checkpoint(enabled=False)
        assert unmarked.checkpoint_enabled is False

    def test_with_checkpoint_preserves_all_fields(self) -> None:
        node = Node.agent(
            id="a1",
            name="Agent",
            agent_id="test",
            output_key="out",
            input_mapping={"key": "val"},
        )
        marked = node.with_checkpoint(enabled=True)
        assert marked.ref_id == "test"
        assert marked.output_key == "out"
        assert marked.input_mapping == {"key": "val"}


# ---------------------------------------------------------------------------
# MarkedNodesPolicy
# ---------------------------------------------------------------------------


class TestMarkedNodesPolicy:
    def test_selects_specified_nodes(self) -> None:
        dag = _build_dag()
        policy = MarkedNodesPolicy(node_ids={"a2", "t4"})
        selected = policy.select_checkpoints(nodes=dag.nodes)
        assert selected == {"a2", "t4"}

    def test_ignores_nonexistent_ids(self) -> None:
        dag = _build_dag()
        policy = MarkedNodesPolicy(node_ids={"a2", "nonexistent"})
        selected = policy.select_checkpoints(nodes=dag.nodes)
        assert selected == {"a2"}

    def test_empty_set(self) -> None:
        dag = _build_dag()
        policy = MarkedNodesPolicy(node_ids=set())
        assert policy.select_checkpoints(nodes=dag.nodes) == set()


# ---------------------------------------------------------------------------
# EveryNNodesPolicy
# ---------------------------------------------------------------------------


class TestEveryNNodesPolicy:
    def test_every_2_nodes(self) -> None:
        dag = _build_dag()
        policy = EveryNNodesPolicy(n=2)
        selected = policy.select_checkpoints(nodes=dag.nodes)
        # 5 executable nodes → checkpoints at positions 2 and 4
        assert len(selected) == 2

    def test_every_1_node(self) -> None:
        dag = _build_dag()
        policy = EveryNNodesPolicy(n=1)
        selected = policy.select_checkpoints(nodes=dag.nodes)
        assert len(selected) == 5  # Every node

    def test_n_larger_than_node_count(self) -> None:
        dag = _build_dag()
        policy = EveryNNodesPolicy(n=100)
        selected = policy.select_checkpoints(nodes=dag.nodes)
        assert len(selected) == 0  # None reach the threshold

    def test_skips_checkpoint_node_types(self) -> None:
        dag = DAG(name="test", description="test")
        dag = dag.add_node(node=Node.agent(id="a1", name="A", agent_id="t1"))
        dag = dag.add_node(node=Node.checkpoint(id="cp"))
        dag = dag.add_node(node=Node.agent(id="a2", name="B", agent_id="t2"))
        policy = EveryNNodesPolicy(n=1)
        selected = policy.select_checkpoints(nodes=dag.nodes)
        # Checkpoint nodes are skipped
        assert "cp" not in selected
        assert len(selected) == 2


# ---------------------------------------------------------------------------
# DAG.with_checkpoint_policy()
# ---------------------------------------------------------------------------


class TestDAGWithCheckpointPolicy:
    def test_applies_policy_to_dag(self) -> None:
        dag = _build_dag()
        policy = MarkedNodesPolicy(node_ids={"a2", "a5"})
        new_dag = dag.with_checkpoint_policy(policy=policy)

        checkpointed = {str(n.id) for n in new_dag.nodes if n.checkpoint_enabled}
        assert checkpointed == {"a2", "a5"}

    def test_original_dag_unchanged(self) -> None:
        dag = _build_dag()
        policy = MarkedNodesPolicy(node_ids={"a2"})
        new_dag = dag.with_checkpoint_policy(policy=policy)

        # Original unchanged (immutable)
        assert not any(n.checkpoint_enabled for n in dag.nodes)
        assert any(n.checkpoint_enabled for n in new_dag.nodes)

    def test_every_n_policy_on_dag(self) -> None:
        dag = _build_dag()
        policy = EveryNNodesPolicy(n=2)
        new_dag = dag.with_checkpoint_policy(policy=policy)

        checkpointed = [n for n in new_dag.nodes if n.checkpoint_enabled]
        assert len(checkpointed) == 2


# ---------------------------------------------------------------------------
# LLMCheckpointPolicy
# ---------------------------------------------------------------------------


class TestLLMCheckpointPolicy:
    def test_sync_fallback_selects_last_and_every_3rd(self) -> None:
        dag = _build_dag()
        policy = LLMCheckpointPolicy(llm_client=None, max_checkpoints=5)
        selected = policy.select_checkpoints(nodes=dag.nodes)
        # Should include the last node
        assert "a5" in selected
        # Should include every 3rd
        assert "a3" in selected

    @pytest.mark.asyncio
    async def test_async_uses_llm_response(self) -> None:
        """LLM returns valid checkpoint list."""
        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = '["a2", "t4"]'
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = mock_message
        mock_client.complete = AsyncMock(return_value=mock_result)

        dag = _build_dag()
        policy = LLMCheckpointPolicy(llm_client=mock_client, max_checkpoints=5)
        selected = await policy.select_checkpoints_async(nodes=dag.nodes)

        assert selected == {"a2", "t4"}
        mock_client.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_falls_back_on_error(self) -> None:
        """LLM failure falls back to sync strategy."""
        mock_client = AsyncMock()
        mock_client.complete = AsyncMock(side_effect=ConnectionError("down"))

        dag = _build_dag()
        policy = LLMCheckpointPolicy(llm_client=mock_client, max_checkpoints=5)
        selected = await policy.select_checkpoints_async(nodes=dag.nodes)

        # Fallback still returns something
        assert len(selected) > 0
        assert "a5" in selected  # Last node always included

    @pytest.mark.asyncio
    async def test_async_ignores_invalid_node_ids(self) -> None:
        """LLM returns IDs that don't exist in DAG — filtered out."""
        mock_client = AsyncMock()
        mock_message = MagicMock()
        mock_message.content = '["a2", "nonexistent", "ghost"]'
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = mock_message
        mock_client.complete = AsyncMock(return_value=mock_result)

        dag = _build_dag()
        policy = LLMCheckpointPolicy(llm_client=mock_client)
        selected = await policy.select_checkpoints_async(nodes=dag.nodes)

        assert selected == {"a2"}  # Only valid ID
