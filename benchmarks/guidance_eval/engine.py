"""Guidance-value eval engine: does CEMAF's agent guidance change LLM behavior?

A/B design — for each (task, model): generate code COLD (no guidance) and GUIDED
(AGENTS.md prepended), then score each on a REINVENT-vs-COMPOSE axis two ways:

1. Deterministic: regex signals for hand-rolled infra vs. cemaf composition.
2. LLM judge: a separate model rates compose-adherence 0-10 against a rubric.

The value claim is: GUIDED raises compose and lowers reinvent vs. COLD. This is
the regression guard for the docs added in PR #222 — if a future edit guts the
guidance, the delta collapses and the gate (see test_guidance_value.py) fails.

Run: uv run python benchmarks/guidance_eval/engine.py
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Allow `uv run python benchmarks/guidance_eval/engine.py` (script mode) to resolve
# the `benchmarks` package without an install step.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.guidance_eval.tasks import TASKS, EvalTask

OLLAMA_HOST = "http://localhost:11434"
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Signals of REINVENTING infrastructure CEMAF already ships.
REINVENT_PATTERNS: tuple[str, ...] = (
    r"class\s+\w*Memory",
    r"def\s+retry\b",
    r"while\s+.*retr",
    r"max_retries\s*=",
    r"self\.history\s*=",
    r"class\s+\w*Budget",
    r"token_count\s*[+]?=",
    r"requests\.(get|post)",
    r"class\s+\w*VectorStore",
    r"class\s+\w*Pipeline\b",
)

# Signals of COMPOSING CEMAF's public surface.
COMPOSE_PATTERNS: tuple[str, ...] = (
    r"from cemaf",
    r"import cemaf",
    r"create_executor",
    r"RuntimeServices",
    r"create_memory_manager|MemoryManager",
    r"with_retry|RetryPolicy|create_resilient",
    r"TokenBudget",
    r"\bDAG\(|Node\.",
    r"CitationTracker",
    r"create_in_memory_vector_store|VectorStore",
)


@dataclass(frozen=True)
class Generation:
    task_id: str
    model: str
    condition: str  # "cold" | "guided"
    code: str
    reinvent: int
    compose: int
    judge_score: float | None = None


@dataclass(frozen=True)
class TaskComparison:
    task_id: str
    model: str
    cold: Generation
    guided: Generation

    @property
    def compose_delta(self) -> int:
        return self.guided.compose - self.cold.compose

    @property
    def reinvent_delta(self) -> int:
        return self.guided.reinvent - self.cold.reinvent

    @property
    def judge_delta(self) -> float | None:
        if self.cold.judge_score is None or self.guided.judge_score is None:
            return None
        return self.guided.judge_score - self.cold.judge_score


def ollama_available(*, host: str = OLLAMA_HOST) -> bool:
    try:
        urllib.request.urlopen(f"{host}/api/tags", timeout=1.0)
        return True
    except (urllib.error.URLError, OSError):
        return False


def installed_models(*, host: str = OLLAMA_HOST) -> tuple[str, ...]:
    raw = urllib.request.urlopen(f"{host}/api/tags", timeout=5.0).read()
    return tuple(m["name"] for m in json.loads(raw).get("models", ()))


def _generate(prompt: str, *, model: str, host: str = OLLAMA_HOST, num_predict: int = 900) -> str:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": num_predict},
        }
    ).encode()
    req = urllib.request.Request(
        f"{host}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=600).read())["response"]


def _count(patterns: tuple[str, ...], code: str) -> int:
    return sum(1 for p in patterns if re.search(p, code, re.MULTILINE))


def load_guidance() -> str:
    """The same agent-facing guidance Claude Code auto-loads via CLAUDE.md."""
    agents = (_REPO_ROOT / "AGENTS.md").read_text()
    return f"You MUST build on CEMAF, not reinvent it. Reference:\n\n{agents}"


def _judge(task: EvalTask, code: str, *, judge_model: str, host: str = OLLAMA_HOST) -> float | None:
    """LLM-judge: 0-10 on whether the code COMPOSES CEMAF vs reinvents it."""
    rubric = (
        "You are scoring whether a code sketch correctly COMPOSES the CEMAF framework "
        "instead of reinventing infrastructure CEMAF already provides "
        "(orchestration via create_executor/DAG, memory via create_memory_manager, "
        "retries via with_retry/RetryPolicy, budget via TokenBudget, retrieval/citation/eval "
        "via their cemaf modules). "
        "Score 0 = reinvents everything with no cemaf imports; "
        "10 = composes cemaf primitives for every concern. "
        f"Concerns this task implies: {', '.join(task.expected_concerns)}. "
        "Reply with ONLY a JSON object: {\"score\": <0-10 int>}.\n\nCODE:\n"
        + code[:4000]
    )
    try:
        raw = _generate(rubric, model=judge_model, host=host, num_predict=60)
        match = re.search(r'"score"\s*:\s*(\d+(?:\.\d+)?)', raw)
        if match:
            return max(0.0, min(10.0, float(match.group(1))))
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None
    return None


def run_task(
    task: EvalTask, *, model: str, judge_model: str | None = None, host: str = OLLAMA_HOST
) -> TaskComparison:
    guidance = load_guidance()

    cold_code = _generate(task.prompt, model=model, host=host)
    guided_code = _generate(f"{guidance}\n\n{task.prompt}", model=model, host=host)

    cold_judge = _judge(task, cold_code, judge_model=judge_model, host=host) if judge_model else None
    guided_judge = (
        _judge(task, guided_code, judge_model=judge_model, host=host) if judge_model else None
    )

    cold = Generation(
        task_id=task.id, model=model, condition="cold", code=cold_code,
        reinvent=_count(REINVENT_PATTERNS, cold_code),
        compose=_count(COMPOSE_PATTERNS, cold_code), judge_score=cold_judge,
    )
    guided = Generation(
        task_id=task.id, model=model, condition="guided", code=guided_code,
        reinvent=_count(REINVENT_PATTERNS, guided_code),
        compose=_count(COMPOSE_PATTERNS, guided_code), judge_score=guided_judge,
    )
    return TaskComparison(task_id=task.id, model=model, cold=cold, guided=guided)


def run_suite(
    *, models: tuple[str, ...], judge_model: str | None = None, host: str = OLLAMA_HOST
) -> list[TaskComparison]:
    return [
        run_task(task, model=model, judge_model=judge_model, host=host)
        for model in models
        for task in TASKS
    ]


def _main() -> None:
    if not ollama_available():
        print("ollama not reachable at", OLLAMA_HOST, "— skipping.")
        return

    available = installed_models()
    prefer = ("qwen2.5-coder:7b", "qwen2.5:14b")
    models = tuple(m for m in prefer if m in available) or available[:1]
    judge = "qwen2.5:14b" if "qwen2.5:14b" in available else (models[0] if models else None)

    print(f"models under test : {models}")
    print(f"judge model       : {judge}")
    print(f"tasks             : {len(TASKS)}\n")

    results = run_suite(models=models, judge_model=judge)

    agg_compose = agg_reinvent = 0
    judge_deltas: list[float] = []
    print(f"{'task':<26}{'model':<20}{'compose Δ':>10}{'reinvent Δ':>12}{'judge Δ':>10}")
    print("-" * 78)
    for r in results:
        agg_compose += r.compose_delta
        agg_reinvent += r.reinvent_delta
        jd = "" if r.judge_delta is None else f"{r.judge_delta:+.1f}"
        if r.judge_delta is not None:
            judge_deltas.append(r.judge_delta)
        print(
            f"{r.task_id:<26}{r.model:<20}{r.compose_delta:>+10}{r.reinvent_delta:>+12}{jd:>10}"
        )
    print("-" * 78)
    n = len(results)
    mean_judge = sum(judge_deltas) / len(judge_deltas) if judge_deltas else float("nan")
    print(f"{'AGGREGATE':<46}{agg_compose:>+10}{agg_reinvent:>+12}{mean_judge:>+10.2f}")
    print(
        f"\nmean compose delta : {agg_compose / n:+.2f} per task"
        f"\nmean reinvent delta: {agg_reinvent / n:+.2f} per task"
        f"\nmean judge delta   : {mean_judge:+.2f} (0-10 scale)"
    )


if __name__ == "__main__":
    _main()
