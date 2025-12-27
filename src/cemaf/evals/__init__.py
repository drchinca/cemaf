"""
Evals module - Evaluation framework for LLM outputs.

Provides:
- Evaluator protocol for pluggable evaluation strategies
- LLM-as-judge evaluation
- Semantic similarity evaluation
- Exact match and regex evaluation
- Composite evaluators
"""

from cemaf.evals.protocols import (
    Evaluator,
    EvalResult,
    EvalMetric,
    EvalConfig,
)
from cemaf.evals.evaluators import (
    ExactMatchEvaluator,
    ContainsEvaluator,
    RegexEvaluator,
    LengthEvaluator,
    JSONSchemaEvaluator,
)
from cemaf.evals.llm_judge import LLMJudgeEvaluator, JudgeCriteria
from cemaf.evals.semantic import SemanticSimilarityEvaluator
from cemaf.evals.composite import CompositeEvaluator, EvalSuite

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

