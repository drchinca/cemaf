"""Checkpoint policies — strategies for auto-selecting which nodes get eval checkpoints.

Usage:
    # Manual: mark specific nodes
    dag = dag.with_checkpoint_policy(MarkedNodesPolicy(node_ids={"n2", "n5"}))

    # Every N nodes
    dag = dag.with_checkpoint_policy(EveryNNodesPolicy(n=3))

    # After high-risk tools
    dag = dag.with_checkpoint_policy(AfterRiskPolicy(min_risk=ToolRiskLevel.HIGH))

    # LLM decides
    dag = dag.with_checkpoint_policy(LLMCheckpointPolicy(llm_client=client))
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from cemaf.core.enums import NodeType, ToolRiskLevel

logger = logging.getLogger(__name__)


@runtime_checkable
class CheckpointPolicy(Protocol):
    """Decides which nodes in a DAG should have checkpoint=True."""

    def select_checkpoints(self, *, nodes: tuple[Any, ...]) -> set[str]:
        """Return node IDs that should be marked as checkpoints."""
        ...


class MarkedNodesPolicy:
    """Checkpoint only the explicitly named nodes."""

    def __init__(self, *, node_ids: set[str]) -> None:
        self._node_ids = node_ids

    def select_checkpoints(self, *, nodes: tuple[Any, ...]) -> set[str]:
        existing_ids = {str(n.id) for n in nodes}
        return self._node_ids & existing_ids


class EveryNNodesPolicy:
    """Checkpoint every N-th node in topological order."""

    def __init__(self, *, n: int = 3, skip_types: set[NodeType] | None = None) -> None:
        self._n = max(1, n)
        self._skip_types = skip_types or {NodeType.CHECKPOINT, NodeType.ROUTER, NodeType.PARALLEL}

    def select_checkpoints(self, *, nodes: tuple[Any, ...]) -> set[str]:
        checkpoints: set[str] = set()
        count = 0
        for node in nodes:
            if node.type in self._skip_types:
                continue
            count += 1
            if count % self._n == 0:
                checkpoints.add(str(node.id))
        return checkpoints


class AfterRiskPolicy:
    """Checkpoint after nodes whose tools have risk >= threshold."""

    def __init__(self, *, min_risk: ToolRiskLevel = ToolRiskLevel.HIGH) -> None:
        self._min_risk = min_risk
        self._risk_order = {
            ToolRiskLevel.LOW: 0,
            ToolRiskLevel.MEDIUM: 1,
            ToolRiskLevel.HIGH: 2,
        }

    def select_checkpoints(self, *, nodes: tuple[Any, ...]) -> set[str]:
        checkpoints: set[str] = set()
        min_level = self._risk_order.get(self._min_risk, 2)
        for node in nodes:
            node_risk = node.config.get("risk_level") if node.config else None
            if node_risk is not None:
                try:
                    risk_enum = ToolRiskLevel(node_risk)
                    if self._risk_order.get(risk_enum, 0) >= min_level:
                        checkpoints.add(str(node.id))
                except ValueError:
                    pass
        return checkpoints


class LLMCheckpointPolicy:
    """LLM decides where to place checkpoints based on DAG structure.

    Requires an LLM client that implements complete(). The LLM receives
    the DAG node list and returns which nodes should be checkpointed.
    """

    def __init__(self, *, llm_client: Any, max_checkpoints: int = 5) -> None:
        self._llm_client = llm_client
        self._max_checkpoints = max_checkpoints

    def select_checkpoints(self, *, nodes: tuple[Any, ...]) -> set[str]:
        """Synchronous wrapper — for async LLM calls, use select_checkpoints_async."""
        # Fallback: checkpoint the last node and every 3rd node
        checkpoints: set[str] = set()
        executable = [n for n in nodes if n.type not in {NodeType.CHECKPOINT, NodeType.ROUTER}]
        if executable:
            checkpoints.add(str(executable[-1].id))
        for i, node in enumerate(executable):
            if (i + 1) % 3 == 0:
                checkpoints.add(str(node.id))
        return set(list(checkpoints)[: self._max_checkpoints])

    async def select_checkpoints_async(self, *, nodes: tuple[Any, ...]) -> set[str]:
        """Ask the LLM where to place checkpoints."""
        from cemaf.llm.protocols import Message

        node_descriptions = []
        for i, node in enumerate(nodes):
            node_descriptions.append(
                f"{i}. [{node.type.value}] id={node.id} name={node.name} ref={node.ref_id}"
            )

        prompt = (
            "You are a quality engineer. Given this DAG execution order, "
            "select which node IDs should have quality checkpoints. "
            "Place checkpoints after critical steps, risky operations, "
            "or before expensive downstream work.\n\n"
            "Nodes:\n" + "\n".join(node_descriptions) + "\n\n"
            f"Return ONLY a JSON list of node IDs to checkpoint "
            f'(max {self._max_checkpoints}). Example: ["n2", "n5"]'
        )

        try:
            result = await self._llm_client.complete(
                messages=[Message.user(content=prompt)],
            )
            if result.success and result.message:
                import json

                content = result.message.content
                if isinstance(content, str):
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        valid_ids = {str(n.id) for n in nodes}
                        return {nid for nid in parsed if nid in valid_ids}
        except Exception as e:
            logger.warning("LLM checkpoint selection failed, using fallback: %s", e)

        return self.select_checkpoints(nodes=nodes)


def apply_checkpoint_policy(
    *,
    nodes: tuple[Any, ...],
    policy: CheckpointPolicy,
) -> tuple[str, ...]:
    """Apply a policy and return the node IDs to checkpoint."""
    return tuple(policy.select_checkpoints(nodes=nodes))
