"""Task corpus for the guidance-value eval.

Each task asks a model to build something on top of CEMAF that, done naively,
tempts the model to hand-roll infrastructure CEMAF already provides. The eval
measures whether the agent-assisted guidance shifts the model from REINVENT to
COMPOSE.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalTask:
    """One prompt plus the CEMAF concerns a good answer should compose."""

    id: str
    prompt: str
    # Concerns the task implies — used by the LLM judge rubric.
    expected_concerns: tuple[str, ...] = field(default_factory=tuple)


_COMMON = "You are building ON TOP OF an existing framework called CEMAF. Output ONLY Python code."

TASKS: tuple[EvalTask, ...] = (
    EvalTask(
        id="pipeline_memory_retry",
        prompt=(
            "Write a sketch of a multi-agent app that runs two agents in a pipeline "
            "(researcher -> writer), keeps memory across turns, retries a flaky tool "
            f"call, and tracks token budget. {_COMMON}"
        ),
        expected_concerns=("orchestration", "memory", "resilience", "budget"),
    ),
    EvalTask(
        id="rag_citations",
        prompt=(
            "Write a sketch of a RAG question-answering app: retrieve from a vector "
            "store, compile an answer within a token budget, and attach citations so "
            f"every claim traces to a source. {_COMMON}"
        ),
        expected_concerns=("retrieval", "context", "citation", "budget"),
    ),
    EvalTask(
        id="quality_gated_writer",
        prompt=(
            "Write a sketch of a content-generation app where an agent's output passes "
            "a quality gate before being accepted; if it fails, the agent retries with "
            f"feedback. Wire it as an orchestrated flow. {_COMMON}"
        ),
        expected_concerns=("orchestration", "evals", "interceptors"),
    ),
    EvalTask(
        id="byo_llm_provider",
        prompt=(
            "I have an internal LLM HTTP gateway. Write a sketch that lets CEMAF drive "
            f"it and runs one agent that calls it. {_COMMON}"
        ),
        expected_concerns=("llm", "agents"),
    ),
)
