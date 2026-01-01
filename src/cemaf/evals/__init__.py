"""
Evals module - Evaluation framework for LLM outputs.

Provides:
- Evaluator protocol for pluggable evaluation strategies
- LLM-as-judge evaluation
- Semantic similarity evaluation
- Exact match and regex evaluation
- Composite evaluators
"""

from cemaf.evals.composite import CompositeEvaluator, EvalSuite
from cemaf.evals.evaluators import (
    ContainsEvaluator,
    ExactMatchEvaluator,
    JSONSchemaEvaluator,
    LengthEvaluator,
    RegexEvaluator,
)
from cemaf.evals.llm_judge import JudgeCriteria, LLMJudgeEvaluator
from cemaf.evals.protocols import (
    EvalConfig,
    EvalMetric,
    EvalResult,
    Evaluator,
)
from cemaf.evals.semantic import SemanticSimilarityEvaluator

__all__ = [
    # Protocols
    "Evaluator",
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
    "EvalSuite",
]
