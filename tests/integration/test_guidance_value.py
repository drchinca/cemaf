"""Regression guard: CEMAF's agent guidance must measurably shift LLMs toward composing.

The docs in PR #222 (AGENTS.md + the agent-assisted guide) exist to stop apps from
using 3-5 modules then reinventing the rest. This test proves they do their job: the
SAME model on the SAME task composes more CEMAF and reinvents less when the guidance
is in context. If a future edit guts the guidance, the delta collapses and this fails.

Runs against a local Ollama daemon; skips with a reason when it's not reachable
(so it never breaks CI on machines without Ollama). It is a behavioral eval, not a
unit test — small task corpus, deterministic-signal scoring, run on the cheapest
installed model to keep it fast.
"""

from __future__ import annotations

import pytest

from benchmarks.guidance_eval.engine import (
    installed_models,
    ollama_available,
    run_task,
)
from benchmarks.guidance_eval.tasks import TASKS

pytestmark = pytest.mark.skipif(
    not ollama_available(),
    reason="Ollama not reachable at localhost:11434 — guidance-value eval needs a local model",
)

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


def test_guidance_increases_composition_over_cold() -> None:
    """GUIDED output composes strictly more CEMAF primitives than COLD output."""
    model = _cheapest_model()

    comparison = run_task(_FLAGSHIP, model=model, judge_model=None)

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
