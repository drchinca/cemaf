"""
TDD Tests for Infinite Loop Prevention in Auto-Healing.

Tests that verify auto-heal doesn't retry indefinitely when:
1. Healing succeeds but doesn't fix the underlying problem
2. Recovery strategy doesn't change context state
3. Node keeps failing with same error
"""

import pytest

from cemaf.context.context import Context
from cemaf.core.recovery import AutoHealManager, RecoveryStrategy
from cemaf.core.result import Result
from cemaf.core.types import NodeID
from cemaf.orchestration.dag import DAG, Node
from cemaf.orchestration.executor import DAGExecutor, NodeResult
from tests.conftest import MockNodeExecutor


class NoOpRecoveryStrategy(RecoveryStrategy):
    """Recovery that succeeds but doesn't actually fix anything."""

    def recover(self, error_result: Result, context: Context) -> Result[Context]:
        """Return success without changing context."""
        return Result.ok(context)


class PermanentFailureNodeExecutor(MockNodeExecutor):
    """Node executor that always fails for specific nodes."""

    def __init__(self, fail_node_ids: set[NodeID]):
        super().__init__()
        self.fail_node_ids = fail_node_ids
        self.attempt_count = 0

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        self.attempt_count += 1
        self.executed.append(str(node.id))

        if node.id in self.fail_node_ids:
            return NodeResult(
                node_id=node.id,
                success=False,
                error="PermanentError: This node always fails",
                metadata={"exception_type": "PermanentError"},
            )

        return NodeResult(
            node_id=node.id,
            success=True,
            output={"status": "ok"},
        )


@pytest.mark.asyncio
async def test_heal_attempt_limit_prevents_infinite_retry():
    """
    GIVEN: A node that fails and has a healing strategy that doesn't fix it
    WHEN: Auto-heal is enabled with default settings
    THEN: Executor should give up after MAX_HEAL_ATTEMPTS, not retry infinitely
    """
    # Setup: Create DAG with single failing node
    dag = DAG(name="test_dag")
    node = Node.tool(
        id="failing_node",
        name="FailingTool",
        tool_id="always_fails",
        output_key="result",
    )
    # Set max_retries and retry_on_failure - need to create new instance
    failing_node_id = node.id
    node = Node(
        id=node.id,
        type=node.type,
        name=node.name,
        ref_id=node.ref_id,
        output_key=node.output_key,
        retry_on_failure=True,
        max_retries=10,
    )
    dag = dag.add_node(node)

    context = Context(data={"attempt_count": 0})

    # Setup: Create executor with auto-heal
    mock_executor = PermanentFailureNodeExecutor(fail_node_ids={failing_node_id})
    executor = DAGExecutor(node_executor=mock_executor)

    # Setup: Register recovery strategy that doesn't fix anything
    auto_heal = AutoHealManager()
    auto_heal.register("PermanentError", NoOpRecoveryStrategy())
    executor._auto_heal_manager = auto_heal

    # Execute: Run DAG (should fail without infinite loop)
    result = await executor.run(dag, context)

    # Assert: Should have limited attempts (not infinite)
    # With MAX_HEAL_ATTEMPTS=2 per node, should be:
    # - Initial attempt: 1
    # - Heal attempt 1: 1 retry
    # - Heal attempt 2: 1 retry
    # - Give up after healing exhausted, only 3 attempts total
    # Expected: < 5 attempts (showing we gave up on healing)
    assert mock_executor.attempt_count < 5, (
        f"Expected < 5 attempts, got {mock_executor.attempt_count} "
        "(indicates infinite loop or ineffective heal limit)"
    )
    # Verify the node actually failed (healing couldn't fix it)
    assert len(result.node_results) > 0
    assert not result.node_results[0].success, "Node should have failed after healing exhausted"


@pytest.mark.asyncio
async def test_heal_must_change_context_to_continue():
    """
    GIVEN: A recovery strategy that claims success but changes nothing
    WHEN: Node is executed with auto-heal enabled
    THEN: Executor should not retry if context didn't actually change
    """
    # Setup: Create DAG
    dag = DAG(name="test_dag")
    node = Node.tool(
        id="test_node",
        name="FailingTool",
        tool_id="failing_tool",
        output_key="result",
    )
    failing_node_id = node.id
    node = Node(
        id=node.id,
        type=node.type,
        name=node.name,
        ref_id=node.ref_id,
        output_key=node.output_key,
        retry_on_failure=True,
        max_retries=5,
    )
    dag = dag.add_node(node)

    context = Context(data={"test": "value"})
    mock_executor = PermanentFailureNodeExecutor(fail_node_ids={failing_node_id})
    executor = DAGExecutor(node_executor=mock_executor)

    # Register recovery that doesn't change context
    auto_heal = AutoHealManager()
    auto_heal.register("PermanentError", NoOpRecoveryStrategy())
    executor._auto_heal_manager = auto_heal

    # Execute
    result = await executor.run(dag, context)

    # Assert: Should not have retried excessively
    # Without fix: Would retry max_retries times (5+)
    # With fix: Should retry limited times (2-3)
    assert mock_executor.attempt_count <= 3, (
        f"Expected <= 3 attempts, got {mock_executor.attempt_count} (healing didn't verify progress)"
    )
    # Verify the node failed (healing couldn't fix it)
    assert len(result.node_results) > 0
    assert not result.node_results[0].success, "Node should have failed"


@pytest.mark.asyncio
async def test_healing_that_changes_context_allows_retry():
    """
    GIVEN: A recovery strategy that actually changes context
    WHEN: Node is executed with auto-heal enabled
    THEN: Executor should retry if context was modified
    """
    context = Context(data={"missing_token": None})

    # Setup: Create DAG
    dag = DAG(name="test_dag")
    node = Node.tool(
        id="api_call",
        name="APIClient",
        tool_id="api_client",
        output_key="result",
    )
    dag = dag.add_node(node)

    # Create custom executor that fails once, then succeeds
    class OnceFailingExecutor(MockNodeExecutor):
        def __init__(self):
            super().__init__()
            self.call_count = 0

        async def execute_node(self, node, context):
            self.call_count += 1
            self.executed.append(str(node.id))

            if self.call_count == 1:
                # First attempt fails
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error="AuthError: Missing API token",
                    metadata={"exception_type": "AuthError"},
                )
            else:
                # After healing, succeeds
                return NodeResult(
                    node_id=node.id,
                    success=True,
                    output={"status": "ok"},
                )

    mock_executor = OnceFailingExecutor()
    executor = DAGExecutor(node_executor=mock_executor)

    # Recovery strategy that actually fixes the problem
    class FixMissingToken(RecoveryStrategy):
        def recover(self, error_result: Result, context: Context) -> Result[Context]:
            # Actually add the missing token
            return Result.ok(context.set("api_token", "recovered_token"))

    auto_heal = AutoHealManager()
    auto_heal.register("AuthError", FixMissingToken())
    executor._auto_heal_manager = auto_heal

    # Execute
    result = await executor.run(dag, context)

    # Assert: Should succeed after recovery fixed the issue
    assert result.success, "DAG should succeed after recovery added missing token"
    assert mock_executor.call_count == 2, "Should have retried once after healing"


@pytest.mark.asyncio
async def test_max_heal_attempts_enforced():
    """
    GIVEN: A node that keeps failing despite repeated healing attempts
    WHEN: MAX_HEAL_ATTEMPTS limit is set
    THEN: Executor should stop healing after limit and fall back to normal retries
    """
    # Setup: Create DAG
    dag = DAG(name="test_dag")
    node = Node.tool(
        id="persistent_fail",
        name="PersistentFail",
        tool_id="always_fails",
        output_key="result",
    )
    failing_node_id = node.id
    node = Node(
        id=node.id,
        type=node.type,
        name=node.name,
        ref_id=node.ref_id,
        output_key=node.output_key,
        retry_on_failure=True,
        max_retries=10,
    )
    dag = dag.add_node(node)

    context = Context(data={"counter": 0})
    mock_executor = PermanentFailureNodeExecutor(fail_node_ids={failing_node_id})
    executor = DAGExecutor(node_executor=mock_executor)

    # Healing that succeeds but doesn't fix
    heal_count = 0

    class CountingRecovery(RecoveryStrategy):
        def recover(self, error_result: Result, context: Context) -> Result[Context]:
            nonlocal heal_count
            heal_count += 1
            # Success, but doesn't fix the underlying issue
            return Result.ok(context.set("heal_count", heal_count))

    auto_heal = AutoHealManager()
    auto_heal.register("PermanentError", CountingRecovery())
    executor._auto_heal_manager = auto_heal

    # Execute
    result = await executor.run(dag, context)

    # Assert: Recovery should have been attempted but limited
    # Expected: 2 heal attempts (max_heal_attempts_per_node = 2)
    assert heal_count <= 2, (
        f"Expected heal_count <= 2, got {heal_count} (max_heal_attempts_per_node not enforced)"
    )
    # Verify the node failed (healing couldn't fix it)
    assert len(result.node_results) > 0
    assert not result.node_results[0].success, "Node should have failed eventually"
