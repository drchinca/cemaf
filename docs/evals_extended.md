# Evals Module - Extended Documentation

## Overview

The evals module provides a framework for evaluating LLM outputs with multiple evaluation strategies (LLM-as-judge, semantic similarity, exact match, regex, JSON schema), supporting metrics collection and composite evaluation suites.

**What it does**: Implements Evaluator protocol for different evaluation approaches. Evaluators take generated output and reference/expected output, return score (0-1) and reasoning. Supports composing multiple evaluators into suites, configuring evaluation criteria, and aggregating results for comprehensive quality assessment.

**Key use cases**:
- Evaluate generation quality (relevance, correctness, tone)
- Compare different models or prompts through benchmarking
- Continuous quality monitoring of production outputs
- A/B testing different agent strategies
- Build evaluation datasets and scoring rubrics
- Measure progress on metrics that matter to business

**When to use vs. alternatives**: Use evals when you need to quantify output quality. Use it for benchmarking and quality tracking. Don't use for functional testing (use unit tests), or when humans will review all outputs anyway.

## Core Concepts

### Evaluation Metrics

**Accuracy/Correctness**: Does output match expected answer? (exact match, fuzzy match)

**Relevance**: Does output address the query/prompt? (semantic similarity, LLM judgment)

**Tone/Style**: Is output in appropriate voice? (LLM judgment with criteria)

**Length**: Is output appropriately sized? (character/word count rules)

**Structure**: Does output follow specified format? (JSON schema, regex)

**Safety**: Does output meet safety requirements? (moderation, policy checks)

### Evaluation Strategies

**Exact Match**: Output == expected. Binary, fast, strict.

**Fuzzy Match**: Output ≈ expected (normalized, ignoring case). Less strict.

**Semantic Similarity**: Embeddings-based similarity. Handles paraphrasing.

**LLM-as-Judge**: Another LLM evaluates with rubric. Most flexible, slower.

**Regex**: Pattern matching. Good for format checking.

**JSON Schema**: Structural validation. Good for structured outputs.

Each evaluator returns:
- Score: 0.0-1.0 (0 = fail, 1 = perfect)
- Reasoning: Why this score (for debugging)

### EvalSuite

Combine multiple evaluators for comprehensive assessment:

```python
suite = EvalSuite([
    ExactMatchEvaluator(),       # Is answer correct?
    SemanticSimilarityEvaluator(), # Is it similar in meaning?
    LLMJudgeEvaluator(criteria=[   # General quality assessment
        "Is response helpful?",
        "Is response accurate?",
        "Is tone appropriate?"
    ]),
    LengthEvaluator(min=50, max=500), # Length constraints
])

# Run suite on output
scores = await suite.evaluate(
    output="Generated response",
    expected="Expected reference",
    context="Original prompt"
)

# Aggregate results
overall_score = sum(scores.values()) / len(scores)
```

## Usage Examples

### Basic Output Evaluation

```python
from cemaf.evals import ExactMatchEvaluator, SemanticSimilarityEvaluator

# Exact match for factual data
exact = ExactMatchEvaluator()
score = await exact.evaluate(
    output="Paris",
    expected="Paris"
)
print(f"Exact match score: {score}")  # 1.0

# Semantic match for varied responses
semantic = SemanticSimilarityEvaluator()
score = await semantic.evaluate(
    output="The capital of France is Paris.",
    expected="Paris is the capital of France."
)
print(f"Semantic similarity: {score:.2f}")  # ~0.95
```

### LLM-as-Judge Evaluation

```python
from cemaf.evals import LLMJudgeEvaluator, JudgeCriteria

# Evaluate with another LLM
judge = LLMJudgeEvaluator(
    criteria=[
        JudgeCriteria(
            name="accuracy",
            description="Is the information factually correct?",
            weight=0.5
        ),
        JudgeCriteria(
            name="helpfulness",
            description="Does it answer the question well?",
            weight=0.3
        ),
        JudgeCriteria(
            name="tone",
            description="Is the tone appropriate and professional?",
            weight=0.2
        ),
    ]
)

result = await judge.evaluate(
    output="...",
    expected="...",
    context="Original prompt"
)

print(f"Score: {result.score:.2f}")
print(f"Reasoning: {result.reasoning}")
```

### Comprehensive Evaluation Suite

```python
from cemaf.evals import EvalSuite, CompositeEvaluator

# Build evaluation suite
evaluators = [
    # Structure validation
    JSONSchemaEvaluator(schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "tags": {"type": "array"}
        },
        "required": ["title", "body"]
    }),

    # Format validation
    RegexEvaluator(pattern=r"^[A-Z].*\.$"),  # Starts upper, ends with period

    # Content validation
    LengthEvaluator(min_chars=100, max_chars=1000),
    ContainsEvaluator(required_keywords=["product", "feature"]),

    # Quality judgment
    LLMJudgeEvaluator(criteria=[
        "Is this engaging?",
        "Is it grammatically correct?",
        "Does it match brand voice?"
    ]),
]

suite = EvalSuite(evaluators)

# Evaluate output
output = "Product Feature: Amazing new capability that improves user experience."
expected = "Expected marketing copy"

results = await suite.evaluate(
    output=output,
    expected=expected
)

# Review results
print(f"Overall score: {results.overall_score:.2f}")
for eval_name, score in results.per_evaluator.items():
    print(f"  {eval_name}: {score:.2f}")
```

### Benchmarking Different Models

```python
from cemaf.evals import EvalSuite

async def benchmark_models(prompts, expected_outputs):
    """Compare generation quality across models."""

    models = ["gpt-4", "gpt-3.5-turbo", "claude-3-5-sonnet"]
    suite = EvalSuite([
        ExactMatchEvaluator(),
        SemanticSimilarityEvaluator(),
        LLMJudgeEvaluator(criteria=["correctness", "clarity"])
    ])

    results = {}

    for model in models:
        scores = []

        for prompt, expected in zip(prompts, expected_outputs):
            # Generate with model
            output = await llm.generate(prompt, model=model)

            # Evaluate
            score = await suite.evaluate(output, expected)
            scores.append(score.overall_score)

        # Average across all prompts
        avg_score = sum(scores) / len(scores)
        results[model] = avg_score

    # Compare
    best_model = max(results, key=results.get)
    print(f"Benchmark Results:")
    for model, score in sorted(results.items(), key=lambda x: x[1], reverse=True):
        print(f"  {model}: {score:.3f}")
    print(f"\nBest: {best_model}")

    return results
```

### Building Evaluation Datasets

```python
from cemaf.evals import EvalDataset

# Create dataset of test cases
dataset = EvalDataset(
    name="social_posts",
    description="Social media post generation",
    examples=[
        {
            "prompt": "Write a Twitter post about our new feature",
            "expected": "Just shipped our new AI-powered search! 🚀",
            "metrics": ["length", "tone", "engagement"]
        },
        {
            "prompt": "Write a LinkedIn article about AI trends",
            "expected": "The Future of AI in Enterprise...",
            "metrics": ["correctness", "formality", "length"]
        },
        ...
    ]
)

# Evaluate all examples
results = await dataset.evaluate(
    generator=lambda prompt: llm.generate(prompt),
    suite=evaluation_suite
)

# Analysis
print(f"Average score: {results.average_score:.3f}")
print(f"Variance: {results.variance:.3f}")

for example_id, scores in results.per_example.items():
    print(f"Example {example_id}: {scores.overall_score:.2f}")
```

### Custom Evaluator

```python
from cemaf.evals.protocols import Evaluator, EvalResult

class ToneEvaluator(Evaluator):
    """Evaluate if output matches target tone."""

    def __init__(self, target_tone: str):
        self.target_tone = target_tone
        self.tone_keywords = {
            "professional": ["hereby", "regarding", "upon", "furthermore"],
            "casual": ["hey", "cool", "amazing", "awesome", "lol"],
            "humorous": ["hilarious", "funny", "witty", "laugh", "joke"],
        }

    async def evaluate(
        self,
        output: str,
        expected: str | None = None,
        context: str | None = None
    ) -> EvalResult:
        """Evaluate tone match."""
        keywords = self.tone_keywords.get(self.target_tone, [])

        # Count matching keywords
        matches = sum(
            output.lower().count(kw.lower())
            for kw in keywords
        )

        # Calculate score
        score = min(1.0, matches / max(1, len(keywords)))

        return EvalResult(
            score=score,
            reasoning=f"Found {matches}/{len(keywords)} tone indicators for '{self.target_tone}'"
        )

# Use custom evaluator
tone_eval = ToneEvaluator("professional")
result = await tone_eval.evaluate("Hereby attached is our proposal...")
print(f"Tone score: {result.score:.2f}")
```

### Continuous Evaluation in Production

```python
from cemaf.evals import EvalSuite
from cemaf.observability.metrics import MetricsCollector

# Evaluate production outputs
class ProductionEvaluator:
    def __init__(self, suite: EvalSuite, metrics: MetricsCollector):
        self.suite = suite
        self.metrics = metrics

    async def evaluate_output(self, output: str, expected: str):
        """Evaluate production output and track metrics."""
        result = await self.suite.evaluate(output, expected)

        # Track metrics
        self.metrics.record_eval_result(
            overall_score=result.overall_score,
            per_evaluator=result.per_evaluator
        )

        # Alert if quality drops
        if result.overall_score < 0.7:
            await alerter.alert(
                level="warning",
                message=f"Output quality low: {result.overall_score:.2f}"
            )

        return result

# Monitor quality over time
evaluator = ProductionEvaluator(suite, metrics)

for output in production_outputs:
    await evaluator.evaluate_output(output, expected)
```

### Common Mistake: Single Evaluator

```python
# ❌ WRONG - Only one evaluation method
score = await exact_match.evaluate(output, expected)
if score > 0.5:
    publish(output)

# ✅ CORRECT - Multiple perspectives
suite = EvalSuite([
    ExactMatchEvaluator(),
    SemanticSimilarityEvaluator(),
    LLMJudgeEvaluator(criteria=[...])
])

result = await suite.evaluate(output, expected)
if result.overall_score > 0.7:
    publish(output)
```

## Integration

### With Generation Module

```python
from cemaf.generation import ImageGenerator
from cemaf.evals import EvalSuite

async def generate_and_evaluate(spec):
    """Generate image and evaluate quality."""
    # Generate
    output = await image_generator.generate(spec)

    # Evaluate (with reference image)
    suite = EvalSuite([
        SemanticSimilarityEvaluator(),
        LLMJudgeEvaluator(criteria=["visual_appeal", "relevance"])
    ])

    eval_result = await suite.evaluate(
        output.url,
        expected=spec.reference_url
    )

    return {
        "image": output,
        "quality_score": eval_result.overall_score
    }
```

### With Persistence

```python
# Store evaluation results
from cemaf.persistence.entities import Run

run = Run(
    project_id=project_id,
    pipeline="content_generation",
    outputs={...},
    evals={
        "overall_score": 0.87,
        "per_evaluator": {
            "semantic_similarity": 0.92,
            "llm_judge": 0.82
        }
    }
)

await run_store.create(run)
```

### With Observability

```python
from cemaf.observability.metrics import MetricsCollector

metrics = MetricsCollector()

result = await suite.evaluate(output, expected)

metrics.record_evaluation(
    evaluator="content_quality",
    score=result.overall_score,
    details=result.per_evaluator
)
```

## API Reference

### Evaluator Protocol

```python
@runtime_checkable
class Evaluator(Protocol):
    async def evaluate(
        self,
        output: str,
        expected: str | None = None,
        context: str | None = None
    ) -> EvalResult: ...
```

### EvalResult

```python
@dataclass
class EvalResult:
    score: float              # 0.0-1.0
    reasoning: str = ""       # Why this score
    metadata: dict = Field(default_factory=dict)
```

### Built-in Evaluators

```python
class ExactMatchEvaluator(Evaluator):
    """Binary exact match."""

class FuzzyMatchEvaluator(Evaluator):
    """Fuzzy string matching."""

class SemanticSimilarityEvaluator(Evaluator):
    """Embedding-based similarity."""

class LengthEvaluator(Evaluator):
    """Character/word count within bounds."""

class RegexEvaluator(Evaluator):
    """Pattern matching."""

class JSONSchemaEvaluator(Evaluator):
    """Structure validation."""

class ContainsEvaluator(Evaluator):
    """Required keywords/phrases."""

class LLMJudgeEvaluator(Evaluator):
    """LLM-based judgment with criteria."""
```

### EvalSuite

```python
class EvalSuite:
    def __init__(self, evaluators: list[Evaluator]): ...

    async def evaluate(
        self,
        output: str,
        expected: str | None = None,
        context: str | None = None
    ) -> CompositeEvalResult: ...

@dataclass
class CompositeEvalResult:
    overall_score: float
    per_evaluator: dict[str, float]
    per_evaluator_reasoning: dict[str, str]
```

## Best Practices

### Evaluation Strategy Selection

```python
USE_CASES = {
    "factual_qa": [
        ExactMatchEvaluator(),              # Is answer exactly right?
        SemanticSimilarityEvaluator()       # Is meaning preserved?
    ],
    "creative_writing": [
        LLMJudgeEvaluator(criteria=[        # General quality
            "Is it engaging?",
            "Is it well-written?",
            "Does it match style?"
        ]),
        LengthEvaluator(min=500, max=2000)  # Length constraints
    ],
    "code_generation": [
        JSONSchemaEvaluator(schema=...),    # Syntax valid?
        RegexEvaluator(pattern=r"..."),     # Format correct?
        LLMJudgeEvaluator(criteria=[        # Quality
            "Is it efficient?",
            "Is it readable?"
        ])
    ],
    "structured_data": [
        JSONSchemaEvaluator(schema=...),    # Structure
        ContainsEvaluator(required_fields=...) # Required fields
    ]
}
```

### Performance Tips

- **Cache evaluations**: Same output+expected = same score
- **Parallel evaluation**: Run multiple evaluators in parallel
- **Lazy evaluation**: Don't evaluate everything. Sample and extrapolate.
- **Batch LLM judging**: Send multiple evaluations to LLM at once

### Common Pitfalls

**Biased evaluation**: LLM judges can have biases. Use multiple judges.

**Overfitting to eval**: Optimize for metric, not actual quality. Use diverse evals.

**No weighting**: Different evals matter differently. Use weights.

**Evaluation drift**: LLM evaluators change behavior. Track and recalibrate.

### When NOT to Use

- **Simple validation**: Use validation module
- **Human review needed**: Don't try to automate subjective judgment
- **Safety-critical**: Always pair with human review
- **Binary decisions**: Evaluation scores need interpretation

### Evaluation Metrics to Track

```python
CORE_METRICS = {
    "accuracy": "Factual correctness",
    "relevance": "Answer addresses question",
    "clarity": "Easy to understand",
    "completeness": "Covers all aspects",
    "tone": "Appropriate voice/style",
    "safety": "No harmful content",
    "length": "Appropriate length"
}
```
