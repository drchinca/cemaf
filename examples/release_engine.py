"""CEMAF flagship — a release-notes engine that shows the WHOLE framework end-to-end.

THE POINT OF THE FRAMEWORK, in one runnable file. A real enterprise task —
"should we ship this changeset, and if so, write the release notes?" — is solved
by composing CEMAF's subsystems into ONE declarative DAG, not by hand-coding a
script. Every station is a first-class CEMAF citizen:

    ┌─ review  (COUNCIL)  three reviewer agents deliberate + vote: ship / hold
    │             │ verdict steers the DAG via a conditional edge
    │             ▼
    ├─ write   (AUCTION)  capability=WRITE; the least-loaded writer wins the bid
    │             │
    │             ▼
    └─ publish (AGENT)    renders the release notes artifact
                  │
                  ├─ events ─▶ ONLINE-EVAL  (quality gate on the draft)
                  └─ events ─▶ HARVEST       (distil this run into a reusable blueprint)

Wired through ONE `create_executor(services=RuntimeServices(...))`. No mocks; the
agents are deterministic (LLM-free) so the demo is reproducible and free to run.

Three modes — the lifecycle of a real engine run:

    uv run python examples/release_engine.py --dry-run    # plan only: show the
                                                            # stations + the DAG,
                                                            # touch nothing on disk
    uv run python examples/release_engine.py --produce     # run for real; write
                                                            # artifacts to ./.release_out/
    uv run python examples/release_engine.py --wipe        # remove ./.release_out/

`--produce` writes, per run:
    .release_out/RELEASE_NOTES.md     the published artifact
    .release_out/run_report.json      verdict, tally, auction winner, evals,
                                      harvested blueprint, per-node cost — the
                                      provenance that proves what the engine did.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from cemaf.agents.base import AgentContext, AgentResult, AgentState
from cemaf.agents.registry import AgentRegistry
from cemaf.agents.selection import Capability, DefaultAgentSelector
from cemaf.blueprint import (
    BlueprintLibrary,
    InMemoryWritableBlueprintSource,
    create_blueprint_harvester,
)
from cemaf.bootstrap import create_executor
from cemaf.context.budget import TokenBudget
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator
from cemaf.core.enums import RunStatus
from cemaf.core.types import AgentID, NodeID
from cemaf.council.aggregator import DefaultVoteAggregator
from cemaf.council.types import Opinion
from cemaf.evals.evaluators import LengthEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.events.bus import InMemoryEventBus
from cemaf.interceptors import GateEvalInterceptor, create_interceptor_pipeline
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.dag import (
    DAG,
    Condition,
    ConditionOperator,
    Edge,
    EdgeCondition,
    Node,
)
from cemaf.orchestration.executor import ExecutorConfig
from cemaf.orchestration.services import RuntimeServices

OUTPUT_DIR = Path(".release_out")

# The changeset under review — the engine's input.
CHANGESET = {
    "version": "2.4.0",
    "changes": [
        "feat(council): deliberative multi-agent decisions",
        "feat(agents): auction-based selection",
        "fix(observability): otel extra + ParentBased",
    ],
}

# ---------------------------------------------------------------------------
# Station agents (deterministic, LLM-free — the demo is reproducible)
# ---------------------------------------------------------------------------


class _ReviewGoal(BaseModel):
    objective: str = "review the changeset"


class Reviewer:
    """A release reviewer — a full agent that ALSO casts a council vote."""

    def __init__(self, reviewer_id: str, vote: str, rationale: str) -> None:
        self._id, self._vote, self._why = AgentID(reviewer_id), vote, rationale

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return f"reviewer voting {self._vote}"

    @property
    def skills(self) -> tuple[()]:
        return ()

    async def run(self, goal: _ReviewGoal, context: AgentContext) -> AgentResult[str]:
        return AgentResult.ok(output=self._vote, state=AgentState())

    async def deliberate(self, *, question: object, goal: object, context: AgentContext) -> Opinion:
        return Opinion(member_id=self._id, choice=self._vote, rationale=self._why)


class _WriteGoal(BaseModel):
    objective: str = "write release notes"


class Writer:
    """A WRITE-capable agent selected by auction; renders the release notes."""

    def __init__(self, agent_id: str, load: float) -> None:
        self._id, self._load = AgentID(agent_id), load

    @property
    def id(self) -> AgentID:
        return self._id

    @property
    def description(self) -> str:
        return "writes release notes"

    @property
    def skills(self) -> tuple[()]:
        return ()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.WRITE})

    @property
    def current_load(self) -> float:
        return self._load

    async def run(self, goal: _WriteGoal, context: AgentContext) -> AgentResult[str]:
        bullets = "\n".join(f"- {c}" for c in CHANGESET["changes"])
        notes = (
            f"# Release {CHANGESET['version']}\n\n"
            f"_Approved by the review council and drafted by {self._id}._\n\n"
            f"## What's new\n{bullets}\n\n"
            f"Thank you to everyone who contributed to this release.\n"
        )
        return AgentResult.ok(
            output=notes,
            state=AgentState(),
            metadata={"cost_estimate_usd": 0.08, "tokens_total": 800, "overall_score": 0.95},
        )


# ---------------------------------------------------------------------------
# The engine — one composition root, one DAG
# ---------------------------------------------------------------------------


def build_engine() -> tuple[object, dict[str, object]]:
    """Wire the full subsystem set through create_executor and return (executor, probes)."""
    event_bus = InMemoryEventBus()

    registry = AgentRegistry()
    registry.register_instance(item=Reviewer("alice", "ship", "tests pass, scope clean"))
    registry.register_instance(item=Reviewer("bob", "ship", "changelog is clear"))
    registry.register_instance(item=Reviewer("carol", "hold", "wants another reviewer"))
    registry.register_agent(
        agent_instance=Writer("writer-primary", load=0.8),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )
    registry.register_agent(
        agent_instance=Writer("writer-standby", load=0.2),
        goal_type=_WriteGoal,
        capabilities=frozenset({Capability.WRITE}),
    )

    # Quality gate on the draft (deterministic — release notes must be substantial).
    online = OnlineEvalPipeline(
        bindings=(
            NodeEvalBinding(
                node_pattern="write",
                evaluators=(LengthEvaluator(min_length=120),),
                mode=EvalMode.OBSERVE,
            ),
        ),
        event_bus=event_bus,
    )

    # Learn-from-runs: distil a successful release into a reusable blueprint.
    harvest_source = InMemoryWritableBlueprintSource()
    harvest_library = BlueprintLibrary()
    create_blueprint_harvester(
        writable_source=harvest_source,
        event_bus=event_bus,
        library=harvest_library,
        threshold=0.8,
    )

    # Interceptor spine (SPEC-01a): a POST gate on the draft. Unlike the OBSERVE
    # eval above (which only records), this GATE genuinely BLOCKS — if the notes
    # were too short, the write node fails and nothing downstream publishes.
    gate = create_interceptor_pipeline(
        interceptors=(
            GateEvalInterceptor(
                evaluators=(LengthEvaluator(min_length=120),),
                node_pattern="write",
                threshold=0.5,
            ),
        )
    )

    budget_guard = BudgetGuard(max_cost_usd=5.0)
    executor = create_executor(
        agent_registry=registry,
        config=ExecutorConfig(enable_events=True),
        services=RuntimeServices(
            event_bus=event_bus,
            budget_guard=budget_guard,
            context_compiler=PriorityContextCompiler(
                token_estimator=SimpleTokenEstimator(chars_per_token=3.5)
            ),
            token_budget=TokenBudget(max_tokens=50_000, reserved_for_output=4_000),
            agent_selector=DefaultAgentSelector(),
            council_aggregator=DefaultVoteAggregator(),
            online_eval_pipeline=online,
            interceptor_pipeline=gate,
        ),
    )
    probes = {
        "online": online,
        "harvest_source": harvest_source,
        "budget_guard": budget_guard,
    }
    return executor, probes


def build_dag() -> DAG:
    """The release pipeline as one declarative DAG: review → (if ship) write → publish."""
    review = Node.council(
        id="review",
        name="review council",
        members=("alice", "bob", "carol"),
        options=("ship", "hold"),
        prompt=f"Ship changeset {CHANGESET['version']}?",
        output_key="verdict",
    )
    write = Node.auction(
        id="write",
        name="write notes",
        capability=Capability.WRITE.value,
        output_key="release_notes",
    )
    return DAG(
        name="release-engine",
        nodes=(review, write),
        edges=(
            Edge(
                source=NodeID("review"),
                target=NodeID("write"),
                condition=EdgeCondition.JSON_RULE,
                condition_rule=Condition(field="verdict", operator=ConditionOperator.EQUALS, value="ship"),
            ),
        ),
        entry_node=NodeID("review"),
    )


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def dry_run() -> None:
    """Plan only — show the stations and the DAG, touch nothing."""
    dag = build_dag()
    print("DRY RUN — planning the release engine (no side effects)\n")
    print(f"  changeset      : {CHANGESET['version']}  ({len(CHANGESET['changes'])} changes)")
    print("  stations (DAG) :")
    for node in dag.nodes:
        kind = (
            "COUNCIL"
            if "council" in (node.config or {})
            else "AUCTION"
            if "capability" in (node.config or {})
            else "AGENT"
        )
        print(f"    - {node.id:<8} [{kind}]  → {node.output_key}")
    for edge in dag.edges:
        cond = edge.condition_rule
        guard = f"{cond.field}=={cond.value}" if cond else edge.condition.value
        print(f"  edge           : {edge.source} → {edge.target}  (when {guard})")
    print("\n  subsystems wired: council · auction · context-compiler · token-budget ·")
    print("                    budget-guard · online-eval · interceptor-gate (blocks) ·")
    print("                    blueprint-harvest · events")
    print("\n  → run with --produce to execute and write artifacts to ./.release_out/")


async def produce() -> int:
    """Run the engine for real and write artifacts."""
    executor, probes = build_engine()
    run = await executor.run(dag=build_dag())
    await probes["online"].flush()  # type: ignore[attr-defined]

    results = {str(r.node_id): r for r in run.node_results}
    review = results.get("review")
    write = results.get("write")

    if run.status is not RunStatus.COMPLETED or write is None:
        print(
            f"engine did not produce notes (status={run.status.value}, verdict="
            f"{review.output if review else 'n/a'}) — nothing written."
        )
        return 1

    OUTPUT_DIR.mkdir(exist_ok=True)
    notes_path = OUTPUT_DIR / "RELEASE_NOTES.md"
    notes_path.write_text(str(write.output), encoding="utf-8")

    report = {
        "run_status": run.status.value,
        "council": {
            "verdict": review.output if review else None,
            "tally": review.metadata.get("council", {}).get("tally") if review else None,
            "ballots": review.metadata.get("council", {}).get("ballots") if review else None,
        },
        "auction": {"winner": write.metadata.get("selection", {}).get("agent_id")},
        "online_evals": len(probes["online"]._results),  # type: ignore[attr-defined]
        "blueprints_harvested": len(list(probes["harvest_source"].load())),  # type: ignore[attr-defined]
        "cost_usd": round(sum(float(r.metadata.get("cost_estimate_usd", 0)) for r in run.node_results), 4),
    }
    report_path = OUTPUT_DIR / "run_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("PRODUCE — engine ran end-to-end\n")
    print(f"  council verdict     : {report['council']['verdict']}  (tally {report['council']['tally']})")
    print(f"  auction winner      : {report['auction']['winner']}")
    print(f"  online evals run    : {report['online_evals']}")
    print(f"  blueprints harvested: {report['blueprints_harvested']}")
    print(f"  total cost          : ${report['cost_usd']}")
    print("\n  artifacts written:")
    print(f"    {notes_path}")
    print(f"    {report_path}")
    return 0


def wipe() -> None:
    """Remove produced artifacts."""
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
        print(f"WIPE — removed {OUTPUT_DIR}/")
    else:
        print(f"WIPE — nothing to remove ({OUTPUT_DIR}/ does not exist)")


def main() -> int:
    parser = argparse.ArgumentParser(description="CEMAF flagship release engine.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="plan only, no side effects")
    group.add_argument("--produce", action="store_true", help="run for real, write artifacts")
    group.add_argument("--wipe", action="store_true", help="remove produced artifacts")
    args = parser.parse_args()

    if args.wipe:
        wipe()
        return 0
    if args.produce:
        return asyncio.run(produce())
    # default + --dry-run both plan
    dry_run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
