"""Evaluation framework — deterministic + LLM-judge + online pipeline.

Three tiers of evaluation that compose:

1. **Deterministic** (cheap, exact): `ExactMatch`, `Contains`, `Regex`,
   `JsonValid`, `Length`, `GroundednessEvaluator` (n-gram overlap for
   hallucination detection), `ToolUseSuccessEvaluator` (tool call success
   rate × result-reference in output).
2. **Semantic** (embedding similarity): `SemanticSimilarityEvaluator`.
3. **LLM-as-judge** (expensive, flexible): `LLMJudgeEvaluator` with
   `JudgeCriteria` (HELPFULNESS, COHERENCE, RELEVANCE, FACTUALITY, SAFETY).

`HierarchicalJudge` escalates from tier-1 to tier-3 only when earlier
tiers don't resolve the question — bounded cost.

Online pipeline:
- `OnlineEvalPipeline` subscribes to `TASK_COMPLETED` events on the EventBus
  and runs bound `Evaluator`s per node.
- `QualityPolice` watches a rolling window of scores and raises a
  `HaltSignal(reason=QUALITY_DEGRADED)` if quality drops below threshold.
- Dogfood: `RunEvalTool`, `CheckQualityTool`, `RecordScoreTool`,
  `QualityGuardAgent` — CEMAF eval primitives registered as CEMAF tools.

Usage:
    from cemaf.evals.evaluators import ExactMatchEvaluator
    from cemaf.evals.grounding import GroundednessEvaluator
    from cemaf.evals.online import OnlineEvalPipeline, NodeEvalBinding, EvalMode

    pipeline = OnlineEvalPipeline(event_bus=bus, bindings=[
        NodeEvalBinding(
            node_id="writer",
            evaluator=GroundednessEvaluator(n=3),
            mode=EvalMode.OBSERVE,
        ),
    ])
    pipeline.subscribe()
"""

from cemaf.evals.agents import QualityGuardAgent, QualityGuardGoal, QualityGuardResult
from cemaf.evals.composite import (
    AggregationStrategy,
    CompositeEvalResult,
    CompositeEvaluator,
    EvalCase,
    EvalSuite,
    EvalSuiteResult,
)
from cemaf.evals.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    JSONSchemaEvaluator,
    LengthEvaluator,
    RegexEvaluator,
)
from cemaf.evals.factories import (
    create_composite_evaluator,
    create_composite_evaluator_from_config,
    create_evaluator,
    create_exact_match_evaluator,
    create_node_eval_binding,
    create_online_eval_pipeline,
    create_quality_police,
    create_single_node_eval_pipeline,
    evaluator_registry,
)
from cemaf.evals.hierarchy import HierarchicalJudge, HierarchicalJudgeConfig, TierResult
from cemaf.evals.llm_judge import JudgeCriteria, LLMJudgeEvaluator
from cemaf.evals.online import EvalMode, NodeEvalBinding, OnlineEvalPipeline
from cemaf.evals.police import AlertLevel, QualityAlert, QualityPolice, QualityPoliceConfig
from cemaf.evals.protocols import (
    BaseEvaluator,
    EvalConfig,
    EvalMetric,
    EvalResult,
    Evaluator,
)
from cemaf.evals.semantic import MultiReferenceSemanticEvaluator, SemanticSimilarityEvaluator
from cemaf.evals.tools import (
    BUILTIN_EVALUATORS,
    CheckQualityTool,
    RecordScoreTool,
    RunEvalTool,
    resolve_evaluators,
)

__all__ = [
    # Protocols
    "Evaluator",
    "BaseEvaluator",
    "EvalResult",
    "EvalMetric",
    "EvalConfig",
    # Basic evaluators
    "ExactMatchEvaluator",
    "ContainsEvaluator",
    "RegexEvaluator",
    "LengthEvaluator",
    "JSONSchemaEvaluator",
    # Advanced evaluators
    "LLMJudgeEvaluator",
    "JudgeCriteria",
    "SemanticSimilarityEvaluator",
    "MultiReferenceSemanticEvaluator",
    # Composite
    "CompositeEvaluator",
    "CompositeEvalResult",
    "AggregationStrategy",
    "EvalCase",
    "EvalSuite",
    "EvalSuiteResult",
    # Hierarchical
    "HierarchicalJudge",
    "HierarchicalJudgeConfig",
    "TierResult",
    # Online eval
    "OnlineEvalPipeline",
    "NodeEvalBinding",
    "EvalMode",
    # Quality police
    "QualityPolice",
    "QualityPoliceConfig",
    "QualityAlert",
    "AlertLevel",
    # Factories
    "create_exact_match_evaluator",
    "create_evaluator",
    "evaluator_registry",
    "create_composite_evaluator",
    "create_composite_evaluator_from_config",
    "create_node_eval_binding",
    "create_online_eval_pipeline",
    "create_quality_police",
    "create_single_node_eval_pipeline",
    # Eval tools (dogfooding)
    "RunEvalTool",
    "CheckQualityTool",
    "RecordScoreTool",
    "resolve_evaluators",
    "BUILTIN_EVALUATORS",
    # Quality guard agent
    "QualityGuardAgent",
    "QualityGuardGoal",
    "QualityGuardResult",
]
