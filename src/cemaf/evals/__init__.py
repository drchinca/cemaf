"""
Evals module - Evaluation framework for LLM outputs.

Provides:
- Evaluator protocol for pluggable evaluation strategies
- LLM-as-judge evaluation
- Semantic similarity evaluation
- Exact match and regex evaluation
- Composite evaluators
"""

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
    create_exact_match_evaluator,
    create_numeric_evaluator,
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
from cemaf.evals.semantic import SemanticSimilarityEvaluator

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
    "create_numeric_evaluator",
    "create_composite_evaluator",
    "create_composite_evaluator_from_config",
]
