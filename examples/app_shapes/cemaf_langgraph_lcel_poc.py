"""App shape: CEMAF outer DAG with a LangGraph/LCEL adapter node.

Use-case: keep CEMAF as the orchestration substrate while reusing a real
LangGraph workflow and LCEL runnables inside one CEMAF node. This mirrors the
BrightAgent Studio shape:

    CEMAF DAG
        -> RuntimeServices(EventBus, RunLogger)
        -> adapter node
        -> LangGraph state graph
        -> LCEL runnables where useful

Run:
    uv run --with langchain-core --with langgraph \
      python examples/app_shapes/cemaf_langgraph_lcel_poc.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from time import perf_counter
from typing import Any, TypedDict

from cemaf.context.context import Context
from cemaf.core.enums import NodeType
from cemaf.core.types import NodeID, RunID
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.observability.run_logger import InMemoryRunLogger
from cemaf.orchestration.dag import DAG, Edge, Node
from cemaf.orchestration.executor import DAGExecutor, ExecutorConfig
from cemaf.orchestration.results import NodeResult
from cemaf.orchestration.services import RuntimeServices
from cemaf.replay.replayer import Replayer, ReplayMode

DEFAULT_PROMPT = (
    "Evaluate whether CEMAF should orchestrate BrightAgent Studio. "
    "Do not judge only speed. Include assertiveness, health, self-recovery, "
    "audit log, traceability, reproducibility, hallucination controls, "
    "insightfulness, and proactivity."
)

SIGNAL_ALIASES: dict[str, tuple[str, ...]] = {
    "assertiveness": ("assertive", "assertiveness", "assertivenes"),
    "health": ("health", "healthy", "healthcheck"),
    "self_recovery": ("self-recovery", "self recovery", "recover", "healing"),
    "auditability": ("audit", "audit log", "run log"),
    "traceability": ("traceability", "trace", "provenance"),
    "reproducibility": ("reproducibility", "replay", "deterministic"),
    "hallucination_control": ("hallucination", "grounded", "citation", "moderation"),
    "insightfulness": ("insight", "insightfulness"),
    "proactivity": ("proactive", "proactivity", "next action"),
}


class StudioGraphState(TypedDict, total=False):
    """State owned by the inner LangGraph workflow."""

    prompt: str
    signals: list[str]
    checks: dict[str, bool]
    recommendation: str
    confidence: float
    next_actions: list[str]


def smoke_skip_reason() -> str | None:
    """Let examples smoke tests skip when optional LangChain deps are absent."""
    missing = [
        package for package in ("langchain_core", "langgraph") if importlib.util.find_spec(package) is None
    ]
    if missing:
        return "optional LangGraph/LCEL dependencies are not installed: " + ", ".join(missing)
    return None


def _require_langchain_deps() -> None:
    reason = smoke_skip_reason()
    if reason is not None:
        command = (
            "uv run --with langchain-core --with langgraph "
            "python examples/app_shapes/cemaf_langgraph_lcel_poc.py"
        )
        raise RuntimeError(f"{reason}. Run with: {command}")


def _extract_signals(prompt: str) -> list[str]:
    lower = prompt.lower()
    return [signal for signal, aliases in SIGNAL_ALIASES.items() if any(alias in lower for alias in aliases)]


def build_langgraph_lcel_app() -> Any:
    """Build a real LangGraph app that uses LCEL internally."""
    _require_langchain_deps()

    from langchain_core.runnables import RunnableLambda, RunnableParallel
    from langgraph.graph import END, START, StateGraph

    extract_signals = RunnableLambda(
        lambda state: {
            "signals": _extract_signals(state["prompt"]),
        }
    )

    quality_checks = RunnableParallel(
        audit_traceability=RunnableLambda(
            lambda state: "auditability" in state["signals"] and "traceability" in state["signals"]
        ),
        reproducibility=RunnableLambda(lambda state: "reproducibility" in state["signals"]),
        recovery_path=RunnableLambda(lambda state: "self_recovery" in state["signals"]),
        hallucination_controls=RunnableLambda(lambda state: "hallucination_control" in state["signals"]),
        health_gate=RunnableLambda(lambda state: "health" in state["signals"]),
        assertive_decision=RunnableLambda(lambda state: "assertiveness" in state["signals"]),
        insight_and_proactivity=RunnableLambda(
            lambda state: "insightfulness" in state["signals"] and "proactivity" in state["signals"]
        ),
    )

    async def extract_node(state: StudioGraphState) -> dict[str, Any]:
        return await extract_signals.ainvoke(state)

    async def assess_node(state: StudioGraphState) -> dict[str, Any]:
        checks = await quality_checks.ainvoke(state)
        confidence = round(sum(1 for passed in checks.values() if passed) / len(checks), 2)
        minimum_ready = all(
            checks[key]
            for key in (
                "audit_traceability",
                "reproducibility",
                "recovery_path",
                "hallucination_controls",
                "health_gate",
            )
        )
        if minimum_ready:
            recommendation = (
                "Use CEMAF as the outer orchestration substrate; run LangGraph, "
                "LCEL, and Studio/DeepAgents-specific skills behind adapter nodes."
            )
        else:
            recommendation = (
                "Do not adopt CEMAF as the outer substrate until the missing operational controls are proven."
            )
        return {
            "checks": checks,
            "confidence": confidence,
            "recommendation": recommendation,
            "next_actions": [
                "Keep speed benchmarks as secondary evidence.",
                "Gate adoption on replay, audit trail, recovery, eval, and groundedness tests.",
                "Keep DeepAgents skills-revision middleware inside the Studio adapter boundary.",
            ],
        }

    graph = StateGraph(StudioGraphState)
    graph.add_node("extract_signals", extract_node)
    graph.add_node("assess_operational_fit", assess_node)
    graph.add_edge(START, "extract_signals")
    graph.add_edge("extract_signals", "assess_operational_fit")
    graph.add_edge("assess_operational_fit", END)
    return graph.compile()


class LangGraphLCELAdapterExecutor:
    """CEMAF node executor that delegates selected nodes to LangGraph/LCEL."""

    def __init__(self, langgraph_app: Any) -> None:
        self._langgraph_app = langgraph_app

    async def execute_node(self, node: Node, context: Context) -> NodeResult:
        start = perf_counter()
        inputs = context.get("_resolved_inputs", default={}) or {}
        role = node.config.get("adapter_role") or node.ref_id

        if role == "langgraph_lcel":
            prompt = str(inputs.get("prompt") or context.get("prompt", ""))
            try:
                output = await self._langgraph_app.ainvoke({"prompt": prompt})
            except Exception as exc:
                return NodeResult(
                    node_id=node.id,
                    success=False,
                    error=str(exc),
                    duration_ms=(perf_counter() - start) * 1000,
                    metadata={"adapter": "langgraph_lcel", "error_type": type(exc).__name__},
                )
            return NodeResult(
                node_id=node.id,
                success=True,
                output=output,
                duration_ms=(perf_counter() - start) * 1000,
                metadata={
                    "adapter": "langgraph_lcel",
                    "inner_runtime": "LangGraph StateGraph + LCEL RunnableParallel",
                    "_context_output": output,
                    "tokens_total": 0,
                    "cost_estimate_usd": 0.0,
                },
            )

        if role == "native_decision":
            assessment = inputs.get("assessment") or {}
            checks = assessment.get("checks", {}) if isinstance(assessment, dict) else {}
            decision = {
                "adopt_cemaf_outer_orchestration": all(
                    bool(checks.get(key))
                    for key in (
                        "audit_traceability",
                        "reproducibility",
                        "recovery_path",
                        "hallucination_controls",
                        "health_gate",
                    )
                ),
                "recommendation": assessment.get("recommendation", ""),
                "confidence": assessment.get("confidence", 0.0),
                "adapter_boundary": "LangGraph/LCEL/DeepAgents stay behind CEMAF nodes.",
            }
            return NodeResult(
                node_id=node.id,
                success=True,
                output=decision,
                duration_ms=(perf_counter() - start) * 1000,
                metadata={"_context_output": decision},
            )

        return NodeResult(
            node_id=node.id,
            success=False,
            error=f"Unknown adapter role: {role}",
            duration_ms=(perf_counter() - start) * 1000,
        )


async def run_poc(prompt: str = DEFAULT_PROMPT) -> dict[str, Any]:
    """Run the PoC and return a compact proof bundle."""
    events: list[Event] = []
    event_bus = InMemoryEventBus()
    event_bus.subscribe_all(lambda event: events.append(event))
    run_logger = InMemoryRunLogger()

    executor = DAGExecutor(
        node_executor=LangGraphLCELAdapterExecutor(build_langgraph_lcel_app()),
        services=RuntimeServices(event_bus=event_bus, run_logger=run_logger),
        config=ExecutorConfig(enable_events=True),
    )

    dag = DAG(
        name="cemaf-langgraph-lcel-poc",
        nodes=(
            Node(
                id=NodeID("studio_adapter"),
                type=NodeType.TOOL,
                name="Studio LangGraph/LCEL Adapter",
                ref_id="langgraph_lcel",
                config={"adapter_role": "langgraph_lcel"},
                input_mapping={"prompt": "$$prompt$$"},
                output_key="studio_assessment",
                structured_output=True,
                checkpoint_enabled=True,
            ),
            Node(
                id=NodeID("cemaf_decision"),
                type=NodeType.TOOL,
                name="CEMAF Native Decision",
                ref_id="native_decision",
                config={"adapter_role": "native_decision"},
                input_mapping={"assessment": "$$studio_assessment$$"},
                output_key="decision",
                structured_output=True,
                checkpoint_enabled=True,
            ),
        ),
        edges=(Edge(source=NodeID("studio_adapter"), target=NodeID("cemaf_decision")),),
        entry_node=NodeID("studio_adapter"),
    )

    result = await executor.run(
        dag=dag,
        initial_context=Context(data={"prompt": prompt, "workspace_id": "studio-poc"}),
        run_id=RunID("poc-cemaf-langgraph-lcel"),
    )
    record = run_logger.get_record(str(result.run_id))
    if record is None:
        raise RuntimeError("RunLogger did not record the PoC run")

    replay_result = await Replayer(record).replay(mode=ReplayMode.PATCH_ONLY)
    event_types = [event.type for event in events]
    patch_paths = [patch.path for patch in record.patches]
    final_context = result.final_context.to_dict()

    return {
        "success": result.success,
        "run_id": str(result.run_id),
        "recommendation": final_context["decision"]["recommendation"],
        "decision": final_context["decision"],
        "quality_checks": final_context["studio_assessment"]["checks"],
        "events": {
            "count": len(events),
            "types": event_types,
            "has_task_events": "task.started" in event_types and "task.completed" in event_types,
            "has_checkpoints": event_types.count("dag.checkpoint"),
        },
        "audit_log": {
            "patch_count": record.total_patches,
            "patch_paths": patch_paths,
            "final_context_keys": sorted(final_context),
        },
        "replay": {
            "success": replay_result.success,
            "patches_applied": replay_result.patches_applied,
            "matches_final_context": replay_result.final_context.data == result.final_context.data,
        },
    }


async def main() -> None:
    summary = await run_poc()
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
