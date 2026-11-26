"""Policy-pilot acceptance at the composition root, including known defects."""

import asyncio
import json

import pytest
from pydantic import BaseModel

from cemaf.agents.base import AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.bootstrap import create_executor
from cemaf.citation.eval import CitationMembershipEvaluator
from cemaf.citation.models import Citation
from cemaf.citation.registry import StaticSourceRegistry
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.context.patch import SecurityLevel
from cemaf.core.enums import MemoryScope
from cemaf.core.types import AgentID, NodeID, RunID
from cemaf.generation.blueprint_request import (
    BlueprintRequest,
    DeliverableType,
    GoalSpec,
    OutputFormat,
    StyleSpec,
)
from cemaf.generation.structured_generator import DefaultStructuredGenerator
from cemaf.interceptors import GateEvalInterceptor, create_interceptor_pipeline
from cemaf.llm.factories import create_instrumented_client
from cemaf.llm.mock import MockLLMClient
from cemaf.llm.protocols import CompletionResult, Message
from cemaf.llm.resilient import ResilientLLMClient
from cemaf.memory.base import InMemoryStore, MemoryItem
from cemaf.observability.budget_guard import BudgetExhaustedError, BudgetGuard
from cemaf.observability.run_logger import InMemoryRunLogger, RunRecord
from cemaf.orchestration.dag import DAG, Edge, EdgeCondition, Node
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode
from cemaf.resilience.circuit_breaker import CircuitBreaker, CircuitConfig
from cemaf.resilience.retry import RetryConfig, RetryPolicy
from cemaf.security.mappings import DictMappingProvider
from cemaf.security.rbac import PermissionDeniedError, RBACEnforcer, RBACMemoryStore
from cemaf.tools.registry import ToolRegistry


class _PolicyGoal(BaseModel):
    source_id: str = "tenant-a/refunds@v2"
    evidence: str = "Returns are accepted within 30 days."
    question: str = "What is the return window?"


class _AnswerAgent:
    id = AgentID("answer")
    description = "Answer a policy question using compiled evidence"
    skills = ()

    def __init__(self, client, *, cited_source_id):
        self.client = client
        self.cited_source_id = cited_source_id

    async def run(self, goal, context):
        compiled = context.artifacts["compiled_context"]
        messages = [Message.system(m["content"]) for m in compiled]
        result = await self.client.complete([*messages, Message.user(goal.question)])
        assert result.success
        citation = Citation(id="refund-policy", source_id=self.cited_source_id, source_type="document")
        return AgentResult.ok(
            output={"answer": result.content, "citations": [citation.to_dict()]}, state=AgentState()
        )


class _PublishAgent:
    id = AgentID("publish")
    description = "Publish only answers accepted by the citation gate"
    skills = ()

    def __init__(self):
        self.calls = 0

    async def run(self, goal, context):
        self.calls += 1
        return AgentResult.ok(output="published", state=AgentState())


class _EmptyGoal(BaseModel):
    pass


def _policy_runtime(source_id, *, budget_guard=None):
    logger = InMemoryRunLogger()
    inner = MockLLMClient(responses=["Returns are accepted within 30 days."])
    client = create_instrumented_client(client=inner, run_logger=logger)
    publish = _PublishAgent()
    registry = AgentRegistry()
    registry.register_agent(
        agent_instance=_AnswerAgent(client, cited_source_id=source_id),
        goal_type=_PolicyGoal,
    )
    registry.register_agent(agent_instance=publish, goal_type=_EmptyGoal)
    gate = GateEvalInterceptor(
        evaluators=(
            CitationMembershipEvaluator(registry=StaticSourceRegistry.from_iterable(["tenant-a/refunds@v2"])),
        ),
        node_pattern="answer",
        threshold=0.5,
    )
    services = RuntimeServices(
        llm_client=client,
        run_logger=logger,
        budget_guard=budget_guard,
        context_compiler=PriorityContextCompiler(token_estimator=SimpleTokenEstimator()),
        token_budget=TokenBudget(max_tokens=1000, reserved_for_output=0),
        interceptor_pipeline=create_interceptor_pipeline(interceptors=(gate,)),
    )
    dag = DAG(
        name="support-policy-acceptance",
        nodes=(
            Node.agent(
                id="answer",
                name="Answer",
                agent_id="answer",
                output_key="draft",
                input_mapping={
                    "source_id": "tenant-a/refunds@v2",
                    "evidence": "Returns are accepted within 30 days.",
                },
            ),
            Node.agent(id="publish", name="Publish", agent_id="publish", output_key="published"),
        ),
        edges=(Edge(source=NodeID("answer"), target=NodeID("publish"), condition=EdgeCondition.ON_SUCCESS),),
        entry_node=NodeID("answer"),
    )
    return (
        create_executor(clearance=SecurityLevel.CONFIDENTIAL, agent_registry=registry, services=services),
        dag,
        logger,
        inner,
        publish,
    )


@pytest.mark.context_acceptance("citation_membership")
@pytest.mark.parametrize(
    "source_id,allowed",
    [
        ("tenant-a/refunds@v2", True),
        ("tenant-a/refunds@v1", False),
        ("tenant-b/refunds@v1", False),
        ("fabricated-policy", False),
    ],
)
async def test_only_selected_policy_revision_can_pass_publication_gate(source_id, allowed):
    executor, dag, logger, client, publish = _policy_runtime(source_id)
    result = await executor.run(dag=dag)
    answer = next(node for node in result.node_results if str(node.node_id) == "answer")
    assert answer.success is allowed
    assert publish.calls == int(allowed)
    assert client.call_count == 1
    if not allowed:
        assert answer.metadata["interceptors"]["gate_rejected"] is True


@pytest.mark.context_acceptance("runtime_replay")
async def test_policy_run_reconstructs_recorded_state_without_model_reexecution():
    executor, dag, logger, client, publish = _policy_runtime("tenant-a/refunds@v2")
    result = await executor.run(dag=dag, run_id=RunID("policy-evidence-run"))
    assert result.success
    assert publish.calls == 1
    record = RunRecord.from_dict(logger.get_history()[0].to_dict())
    assert "tenant-a/refunds@v2" in str(record.llm_calls[0].input_messages)
    assert record.provenance_chain is not None
    assert record.patches
    replay = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
    assert replay.success
    assert replay.final_context.data == record.final_context.data
    draft = json.loads(replay.final_context.get("draft"))
    assert draft["citations"][0]["source_id"] == "tenant-a/refunds@v2"
    assert client.call_count == 1


def _scoped_store(inner):
    provider = DictMappingProvider(
        {
            "users": {
                "reviewer": {
                    "roles": [],
                    "attributes": {"department": "support"},
                    "direct_access": [
                        {"scope": "project", "scope_path_prefix": "/tenant/a/", "actions": ["read", "list"]},
                        {
                            "scope": "project",
                            "scope_path_prefix": "/tenant/b/",
                            "actions": ["read"],
                            "abac_conditions": {"department": "finance"},
                        },
                    ],
                }
            }
        }
    )
    enforcer = RBACEnforcer(provider)
    return RBACMemoryStore(inner=inner, enforcer=enforcer, principal_id="reviewer"), enforcer


@pytest.mark.context_acceptance("abac_list")
async def test_denied_attribute_grant_cannot_expand_visible_policy_list():
    inner = InMemoryStore()
    for tenant in ("a", "b"):
        await inner.set(
            MemoryItem(
                scope=MemoryScope.PROJECT,
                key=f"tenant-{tenant}",
                value={"policy": tenant},
                scope_path=f"/tenant/{tenant}/refunds",
            )
        )
    store, enforcer = _scoped_store(inner)
    assert not enforcer.can("reviewer", "read", MemoryScope.PROJECT, "/tenant/b/refunds")
    items = await store.list_by_scope(MemoryScope.PROJECT)
    assert [item.key for item in items] == ["tenant-a"]


@pytest.mark.context_acceptance("scoped_read")
async def test_permitted_policy_can_be_read_with_a_scoped_grant():
    inner = InMemoryStore()
    await inner.set(
        MemoryItem(
            scope=MemoryScope.PROJECT, key="refunds", value={"window": 30}, scope_path="/tenant/a/refunds"
        )
    )
    store, enforcer = _scoped_store(inner)
    assert enforcer.can("reviewer", "read", MemoryScope.PROJECT, "/tenant/a/refunds")
    denied = False
    try:
        item = await store.get(MemoryScope.PROJECT, "refunds")
    except PermissionDeniedError:
        denied, item = True, None
    assert not denied
    assert item is not None and item.value == {"window": 30}


class _BarrierAgent:
    id = AgentID("barrier")
    description = "Synchronize concurrent policy-answer runs"
    skills = ()

    def __init__(self):
        self.arrivals = 0
        self.release = asyncio.Event()

    async def run(self, goal, context):
        self.arrivals += 1
        if self.arrivals == 2:
            self.release.set()
        await asyncio.wait_for(self.release.wait(), timeout=5)
        return AgentResult.ok(output=context.run_id, state=AgentState())


@pytest.mark.context_acceptance("concurrent_logger")
async def test_concurrent_policy_runs_have_separate_complete_records():
    registry, logger = AgentRegistry(), InMemoryRunLogger()
    registry.register_agent(agent_instance=_BarrierAgent(), goal_type=_EmptyGoal)
    executor = create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        services=RuntimeServices(run_logger=logger),
    )
    dag = DAG(name="concurrent-policy").add_node(
        node=Node.agent(id="barrier", name="Barrier", agent_id="barrier", output_key="answer")
    )
    runs = await asyncio.gather(
        *(executor.run(dag=dag, run_id=RunID(run)) for run in ("run-a", "run-b")), return_exceptions=True
    )
    assert all(not isinstance(run, BaseException) and run.success for run in runs)
    records = {record.run_id: record for record in logger.get_history()}
    assert set(records) == {"run-a", "run-b"}
    assert all(record.final_context.get("answer") == run_id for run_id, record in records.items())


@pytest.mark.context_acceptance("runtime_budget")
async def test_logged_tokens_exhaust_budget_before_second_dispatch():
    guard = BudgetGuard(max_total_tokens=1)
    executor, dag, logger, client, publish = _policy_runtime(
        "tenant-a/refunds@v2",
        budget_guard=guard,
    )
    await executor.run(dag=dag)
    assert logger.get_history()[0].total_tokens > 1
    assert guard.accumulated_tokens == logger.get_history()[0].total_tokens
    assert publish.calls == 0


@pytest.mark.context_acceptance("runtime_budget")
@pytest.mark.parametrize("reports_metadata", [False, True])
async def test_budget_stops_another_call_inside_one_agent_without_double_charging(reports_metadata):
    logger, guard = InMemoryRunLogger(), BudgetGuard(max_total_tokens=1)
    raw = MockLLMClient(responses=["First answer"])
    client = create_instrumented_client(client=raw, run_logger=logger)

    class TwiceAgent:
        id = AgentID("twice")
        description = "Attempt a second billed call"
        skills = ()
        blocked = False

        async def run(self, goal, context):
            first = await client.complete([Message.user("Question")])
            try:
                await client.complete([Message.user("Another question")])
            except BudgetExhaustedError:
                self.blocked = True
            metadata = {"tokens_total": int(first.total_tokens)} if reports_metadata else {}
            return AgentResult.ok(output="done", state=AgentState(), metadata=metadata)

    agent, registry = TwiceAgent(), AgentRegistry()
    registry.register_agent(agent_instance=agent, goal_type=_EmptyGoal)
    executor = create_executor(
        clearance=SecurityLevel.CONFIDENTIAL,
        agent_registry=registry,
        services=RuntimeServices(
            llm_client=client,
            run_logger=logger,
            budget_guard=guard,
        ),
    )
    dag = DAG(name="intra-agent-budget").add_node(
        node=Node.agent(id="answer", name="Answer", agent_id="twice")
    )
    await executor.run(dag=dag)
    assert agent.blocked and raw.call_count == 1
    assert guard.accumulated_tokens == logger.get_history()[0].total_tokens


class _SchemaAnswer(BaseModel):
    answer: str


class _RepairClient(MockLLMClient):
    def __init__(self):
        super().__init__()
        self.limits = []

    async def complete(self, messages, tools=None, config_override=None, **kwargs):
        self.limits.append(config_override.max_tokens)
        text = "invalid json" if len(self.limits) == 1 else '{"answer":"30 days"}'
        return CompletionResult.ok(
            message=Message.assistant(text), completion_tokens=min(4, config_override.max_tokens)
        )


@pytest.mark.context_acceptance("repair_budget")
async def test_schema_repair_uses_only_the_remaining_generation_allowance():
    client = _RepairClient()
    request = BlueprintRequest(
        blueprint_id="policy",
        blueprint_version="1",
        entities=(),
        goal=GoalSpec(objective="Answer", deliverable_type=DeliverableType.ANSWER),
        style=StyleSpec(tone="neutral", max_tokens=5, output_format=OutputFormat.JSON),
        policies=(),
        output_schema=_SchemaAnswer,
        grounding_refs=(),
        schema_repair_budget=1,
    )
    await DefaultStructuredGenerator().generate(request=request, client=client, tool_registry=ToolRegistry())
    assert len(client.limits) == 2
    assert client.limits[0] == 5
    assert 0 < client.limits[1] <= 1


class _UnavailableClient(MockLLMClient):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    async def complete(self, *args, **kwargs):
        self.attempts += 1
        return CompletionResult.fail(error="provider temporarily unavailable (503)")


@pytest.mark.context_acceptance("result_failure_resilience")
async def test_returned_retryable_failures_are_retried_and_counted_by_circuit():
    client = _UnavailableClient()
    breaker = CircuitBreaker(CircuitConfig(failure_threshold=3))
    wrapped = ResilientLLMClient(
        client=client,
        circuit_breaker=breaker,
        retry=RetryPolicy(RetryConfig(max_attempts=3, initial_delay_seconds=0)),
    )
    result = await wrapped.complete([Message.user("Policy question")])
    assert not result.success
    assert client.attempts == 3
    assert breaker.metrics.failed_calls == 3
    assert breaker.is_open
