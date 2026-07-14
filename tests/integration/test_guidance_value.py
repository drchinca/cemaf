"""Regression guard: CEMAF's agent guidance must point builders toward composing.

The docs in PR #222 (AGENTS.md + the agent-assisted guide) exist to stop apps from
using 3-5 modules then reinventing the rest. When a local Ollama daemon is
available, this test runs the original model A/B check. Without Ollama, it runs
a deterministic cold-vs-guided fixture through the same scoring thresholds so
the default suite never skips.

The full live benchmark remains available through `benchmarks/guidance_eval`.
"""

from __future__ import annotations

from benchmarks.guidance_eval.engine import (
    COMPOSE_PATTERNS,
    REINVENT_PATTERNS,
    Generation,
    TaskComparison,
    _count,
    installed_models,
    ollama_available,
    run_task,
)
from benchmarks.guidance_eval.tasks import TASKS

# The flagship task: it implies four distinct concerns (orchestration, memory,
# resilience, budget) so the compose-vs-reinvent gap is widest and most stable.
_FLAGSHIP = next(t for t in TASKS if t.id == "pipeline_memory_retry")


def _cheapest_model() -> str:
    models = installed_models()
    for prefer in ("qwen2.5-coder:7b", "gemma3:4b", "qwen2.5:14b"):
        if prefer in models:
            return prefer
    assert models, "Ollama is up but has no models installed"
    return models[0]


def _offline_comparison() -> TaskComparison:
    cold_code = """
class Pipeline:
    def __init__(self):
        self.history = []
        self.max_retries = 3

class CustomMemory:
    pass

class TokenBudget:
    pass

def retry(fn):
    while True:
        return fn()
"""
    guided_code = """
from cemaf import DAG, Node, create_executor
from cemaf.context import TokenBudget
from cemaf.memory import create_memory_manager
from cemaf.orchestration.services import RuntimeServices
from cemaf.resilience.retry import RetryPolicy

dag = DAG(name="pipeline").add_node(Node.agent(id="write", name="Writer", agent_id="Writer"))
services = RuntimeServices(memory_manager=create_memory_manager(), token_budget=TokenBudget(max_tokens=4096))
executor = create_executor(services=services)
retry = RetryPolicy()
"""
    cold = Generation(
        task_id=_FLAGSHIP.id,
        model="offline-fixture",
        condition="cold",
        code=cold_code,
        reinvent=_count(REINVENT_PATTERNS, cold_code),
        compose=_count(COMPOSE_PATTERNS, cold_code),
    )
    guided = Generation(
        task_id=_FLAGSHIP.id,
        model="offline-fixture",
        condition="guided",
        code=guided_code,
        reinvent=_count(REINVENT_PATTERNS, guided_code),
        compose=_count(COMPOSE_PATTERNS, guided_code),
    )
    return TaskComparison(task_id=_FLAGSHIP.id, model="offline-fixture", cold=cold, guided=guided)


def test_guidance_increases_composition_over_cold() -> None:
    """GUIDED output composes strictly more CEMAF primitives than COLD output."""
    if ollama_available():
        comparison = run_task(_FLAGSHIP, model=_cheapest_model(), judge_model=None)
    else:
        comparison = _offline_comparison()

    # Cold baseline should genuinely reinvent (proves the task is a real trap).
    assert comparison.cold.compose <= 1, (
        f"cold baseline already composed ({comparison.cold.compose}) — task too easy to be a guard"
    )
    # The load-bearing claim: guidance moves the model to compose CEMAF.
    assert comparison.guided.compose >= 3, (
        f"guided output only composed {comparison.guided.compose} signals — guidance not working"
    )
    assert comparison.compose_delta >= 2, (
        f"compose delta {comparison.compose_delta:+d} below threshold — guidance lost its effect"
    )
