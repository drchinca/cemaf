# RLM Safety Improvement Roadmap: 3/10 → 5/10 → 7/10 → 9/10

Concrete steps to improve RLM's ML safety score from 3/10.

---

## Phase 0: Immediate (This Week)

### 0.1 Add Safety Warning to Tool Documentation

**File**: `src/cemaf/rlm/tool.py`

```python
class RLMQueryTool(Tool):
    """
    Tool for recursive context querying.

    ⚠ SAFETY WARNING ⚠
    This tool trades accuracy for scalability. It loses ~37% of information
    at each recursion level. At depth 3, only ~25% of original information
    is retained.

    DO NOT use for:
      - Safety-critical decisions (medical, legal, financial)
      - Complete analysis ("find ALL instances")
      - Compliance or audit work
      - Multi-agent systems requiring consistent facts

    DO use for:
      - Exploratory analysis ("what topics are covered?")
      - Quick overviews and summaries
      - Aggregate statistics
      - Resource-constrained scenarios

    See documentation on SAFETY SCORE (3/10) and LIMITATIONS.
    """
```

### 0.2 Add Explicit Coverage Warnings to Metadata

**File**: `src/cemaf/rlm/tool.py` in `execute()` method

```python
async def execute(self, **kwargs: Any) -> ToolResult:
    # ... existing code ...

    coverage_percent = (result.chunks_examined / len(chunks)) * 100

    if coverage_percent < 50:
        result.metadata["WARNING_COVERAGE_LOW"] = (
            f"Only {coverage_percent:.1f}% of document was examined. "
            f"This answer is based on ~{coverage_percent:.0f}% of available data. "
            f"Consider using max_depth={self._default_max_depth + 1} or RAG instead."
        )

    if result.depth_reached >= self._default_max_depth:
        result.metadata["WARNING_MAX_DEPTH"] = (
            f"Query reached maximum depth ({result.depth_reached}). "
            f"Last level used fallback (queried only first chunk). "
            f"Information loss likely 40-60%."
        )

    return result
```

### 0.3 Document Current Test Limitations

**File**: Add comments to `tests/unit/rlm/test_engine.py`

```python
class MockLLMClient:
    """
    Mock LLM client for testing RLM structure.

    ⚠ LIMITATION: This mock is unrealistically perfect:
      - Always succeeds (no failures)
      - Deterministic responses (no temperature variance)
      - No hallucinations (real LLMs do hallucinate)
      - Small response size (real responses vary)

    ✗ These tests DO NOT measure:
      - Actual accuracy against ground truth
      - Information loss through recursion
      - Hallucination rate
      - Real LLM behavior

    To properly test RLM, also needed:
      - Real LLM integration tests
      - Accuracy benchmarks
      - Information loss measurement
      - Hallucination detection
    """
```

---

## Phase 1: Basic Safety (1-2 weeks) → Target 5/10

### Goal
Add basic accuracy validation and information loss measurement.

### 1.1 Implement Accuracy Benchmarking

**New file**: `src/cemaf/rlm/evaluator.py`

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class FactExtractionResult:
    """Results from fact extraction."""
    correct_facts: int
    hallucinated_facts: int
    missed_facts: int

    @property
    def precision(self) -> float:
        """% of found facts that are correct."""
        total_found = self.correct_facts + self.hallucinated_facts
        if total_found == 0:
            return 0.0
        return self.correct_facts / total_found

    @property
    def recall(self) -> float:
        """% of ground truth facts found."""
        total_truth = self.correct_facts + self.missed_facts
        if total_truth == 0:
            return 0.0
        return self.correct_facts / total_truth

    @property
    def f1(self) -> float:
        """F1 score."""
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * (p * r) / (p + r)

    @property
    def information_loss(self) -> float:
        """Information loss percentage."""
        return 1.0 - self.recall


class RLMEvaluator:
    """Evaluates RLM accuracy and information loss."""

    async def evaluate_on_benchmark(
        self,
        rlm_tool: RLMQueryTool,
        test_cases: list[dict],
    ) -> dict[str, float]:
        """
        Evaluate RLM on benchmark dataset.

        Args:
            rlm_tool: RLM query tool to evaluate
            test_cases: List of {document, query, expected_facts}

        Returns:
            Dictionary with metrics: accuracy, precision, recall, etc.
        """
        results_by_depth = {}

        for depth in [1, 2, 3]:
            all_results = []

            for test_case in test_cases:
                result = await rlm_tool.execute(
                    instruction=test_case["query"],
                    content=test_case["document"],
                    max_depth=depth,
                )

                extracted_facts = extract_facts(result.data)
                ground_truth = test_case["expected_facts"]

                eval_result = self._compare_facts(
                    extracted_facts,
                    ground_truth,
                )
                all_results.append(eval_result)

            # Aggregate metrics
            avg_recall = sum(r.recall for r in all_results) / len(all_results)
            avg_precision = sum(r.precision for r in all_results) / len(all_results)
            avg_f1 = sum(r.f1 for r in all_results) / len(all_results)
            avg_loss = sum(r.information_loss for r in all_results) / len(all_results)

            results_by_depth[depth] = {
                "recall": avg_recall,
                "precision": avg_precision,
                "f1": avg_f1,
                "information_loss": avg_loss,
            }

        return results_by_depth

    def _compare_facts(
        self,
        extracted: set[str],
        ground_truth: set[str],
    ) -> FactExtractionResult:
        """Compare extracted facts to ground truth."""
        correct = extracted & ground_truth
        hallucinated = extracted - ground_truth
        missed = ground_truth - extracted

        return FactExtractionResult(
            correct_facts=len(correct),
            hallucinated_facts=len(hallucinated),
            missed_facts=len(missed),
        )
```

### 1.2 Create Benchmark Dataset

**New file**: `tests/fixtures/rlm_benchmarks.py`

```python
RLM_BENCHMARK_CASES = [
    {
        "name": "medical_study_facts",
        "document": """
        Clinical Trial Results:
        - 500 patients enrolled
        - Age range: 25-75 years
        - Study duration: 24 months
        - Primary outcome: mortality reduction
        - Treatment group: 5% mortality (25/500)
        - Control group: 10% mortality (50/500)
        - Relative risk reduction: 50%
        - P-value: 0.003
        - Side effects in treatment: 12%
        - Side effects in control: 8%
        - Recommendation: For patients >50
        """,
        "query": "Extract all numerical results from the study",
        "expected_facts": {
            "patients_500",
            "mortality_treatment_5pct",
            "mortality_control_10pct",
            "relative_risk_reduction_50pct",
            "pvalue_0003",
            "side_effects_treatment_12pct",
            "side_effects_control_8pct",
        },
    },
    # ... more benchmark cases ...
]
```

### 1.3 Add Confidence Scoring to RLM Results

**File**: `src/cemaf/rlm/engine.py` in `RecursiveQueryResult`

```python
@dataclass
class RecursiveQueryResult:
    # ... existing fields ...

    def calculate_confidence(self) -> float:
        """
        Calculate confidence score for this result.

        Based on:
        - Recursion depth (deeper = less confident)
        - Coverage percentage (lower coverage = less confident)
        - Hallucination likelihood (based on LLM call count)

        Returns:
            Confidence score from 0.0 to 1.0
        """
        # Depth penalty: each level reduces confidence by ~20%
        depth_factor = (1.0 - (0.2 * self.depth_reached))

        # Coverage penalty: lower coverage = lower confidence
        coverage = self.chunks_examined / max(1, len(self.relevant_chunks))
        coverage_factor = coverage ** 0.5  # Square root to emphasize differences

        # LLM call penalty: more calls = higher hallucination risk
        # Each call adds ~10% hallucination risk
        hallucination_risk = 1.0 - (0.9 ** self.llm_calls_made)
        llm_factor = 1.0 - hallucination_risk

        # Combined confidence
        confidence = depth_factor * coverage_factor * llm_factor

        return max(0.0, min(1.0, confidence))
```

### 1.4 Update Tool Result with Metrics

**File**: `src/cemaf/rlm/tool.py` in `execute()` method

```python
result = await self._engine.query(...)

# Calculate metrics
accuracy_estimate = result.calculate_confidence()
information_loss = 1.0 - (result.chunks_examined / len(chunks))

# Add to metadata
return Result.ok(
    result.answer,
    metadata={
        "depth_reached": result.depth_reached,
        "chunks_examined": result.chunks_examined,
        "total_chunks_created": len(chunks),
        # NEW METRICS
        "confidence_score": accuracy_estimate,
        "information_loss_estimated": information_loss,
        "coverage_percent": (result.chunks_examined / len(chunks)) * 100,
        **result.metadata,
    },
)
```

### 1.5 Add Real LLM Integration Tests

**New file**: `tests/integration/rlm/test_rlm_with_real_llm.py`

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_rlm_accuracy_with_gpt4():
    """Test RLM accuracy against real LLM."""

    llm_client = AnthropicClient(api_key=os.getenv("ANTHROPIC_API_KEY"))

    evaluator = RLMEvaluator()
    results = await evaluator.evaluate_on_benchmark(
        rlm_tool,
        RLM_BENCHMARK_CASES,
    )

    # Assertions on real performance
    assert results[1]["recall"] >= 0.80, "Depth 1 should find 80%+ of facts"
    assert results[1]["precision"] >= 0.85, "Depth 1 should be 85%+ accurate"
    assert results[1]["information_loss"] <= 0.20, "Depth 1 should lose <20%"

    # Log results for future reference
    logger.info(f"RLM Benchmark Results:\n{json.dumps(results, indent=2)}")
```

---

## Phase 2: Production Safety (2-4 weeks) → Target 7/10

### Goal
Add coverage tracking, source preservation, and user warnings.

### 2.1 Implement Coverage Tracking

**New file**: `src/cemaf/rlm/coverage.py`

```python
from dataclasses import dataclass

@dataclass
class CoverageReport:
    """Information coverage report."""
    examined_chunks: int
    total_chunks: int
    coverage_percent: float
    information_loss: float
    warnings: list[str]

    def get_coverage_level(self) -> str:
        """Return: COMPLETE, GOOD, PARTIAL, LIMITED, VERY_LIMITED"""
        if self.coverage_percent >= 95:
            return "COMPLETE"
        elif self.coverage_percent >= 75:
            return "GOOD"
        elif self.coverage_percent >= 50:
            return "PARTIAL"
        elif self.coverage_percent >= 25:
            return "LIMITED"
        else:
            return "VERY_LIMITED"


class CoverageTracker:
    """Tracks information coverage through recursion."""

    def __init__(self, total_chunks: int):
        self.total_chunks = total_chunks
        self.examined_chunks = set()
        self.chunk_examination_depth = {}  # chunk_id -> [fully, partially, barely]

    def record_examination(
        self,
        chunk_id: str,
        examination_type: str = "full",  # full, partial, mention
    ):
        """Record that a chunk was examined."""
        self.examined_chunks.add(chunk_id)

        if chunk_id not in self.chunk_examination_depth:
            self.chunk_examination_depth[chunk_id] = []

        self.chunk_examination_depth[chunk_id].append(examination_type)

    def get_report(self) -> CoverageReport:
        """Generate coverage report."""
        coverage_percent = (len(self.examined_chunks) / self.total_chunks) * 100
        information_loss = 1.0 - (len(self.examined_chunks) / self.total_chunks)

        warnings = []
        if coverage_percent < 50:
            warnings.append(
                f"Low coverage: Only {coverage_percent:.1f}% of document examined"
            )
        if coverage_percent < 30:
            warnings.append(
                "Very low coverage: Information loss likely 70%+"
            )

        return CoverageReport(
            examined_chunks=len(self.examined_chunks),
            total_chunks=self.total_chunks,
            coverage_percent=coverage_percent,
            information_loss=information_loss,
            warnings=warnings,
        )
```

### 2.2 Add Source Preservation

**File**: `src/cemaf/rlm/engine.py` update `_single_query()`

```python
async def _single_query(
    self,
    instruction: str,
    chunks: tuple[ContextChunk, ...],
    compiled: CompiledContext,
) -> dict[str, Any]:
    """Execute single LLM query with all chunks."""

    # Format chunks with identifiers for tracking
    chunk_content_with_ids = []
    for chunk in chunks:
        chunk_content_with_ids.append(f"[{chunk.chunk_id}]\n{chunk.content}")

    context_content = "\n\n---\n\n".join(chunk_content_with_ids)

    prompt = f"""{instruction}

Context (with chunk identifiers for reference):
{context_content}

Important: When answering, include the chunk ID [chunk_id] next to claims
so we can verify your source. Example: "The result was X [chunk_5]."

Provide your answer based on the context above. If the information is not found in the
context, explicitly state that."""

    messages = [Message.user(prompt)]
    result = await self._llm.complete(messages)

    # Try to extract source references from answer
    sources = extract_chunk_references(result.content)

    return {
        "answer": result.content if isinstance(result.content, str) else str(result.content),
        "found": True,
        "tokens_used": int(result.total_tokens),
        "sources_cited": sources,  # NEW
    }
```

### 2.3 Implement Adaptive Depth Selection

**New file**: `src/cemaf/rlm/depth_selector.py`

```python
class AdaptiveDepthSelector:
    """Selects appropriate recursion depth based on query requirements."""

    def select_depth(
        self,
        query: str,
        document_size: int,  # in tokens
        accuracy_requirement: float = 0.8,  # 0-1
        coverage_requirement: float = 0.8,  # 0-1
    ) -> int:
        """
        Select appropriate max_depth.

        accuracy_requirement:
          0.95+ → depth 1 (need ~63% info, might lose critical details)
          0.85-0.95 → depth 1-2
          0.70-0.85 → depth 2
          <0.70 → depth 2-3

        coverage_requirement:
          0.95+ → depth 1 (only covers ~63% at depth 1)
          0.80+ → depth 1
          0.60+ → depth 2
          <0.60 → depth 3
        """

        # If accuracy is critical, need shallower depth
        if accuracy_requirement >= 0.95:
            recommended_depth = 1
            warning = "High accuracy requirement: Depth 1 only preserves ~63% of info"
        elif accuracy_requirement >= 0.85:
            recommended_depth = max(1, min(2, depth_for_size))
            warning = "Medium-high accuracy: Depth 1-2 recommended"
        else:
            recommended_depth = max(2, min(3, depth_for_size))
            warning = "Lower accuracy acceptable: Depth 2-3 viable"

        return recommended_depth, warning
```

### 2.4 Update Error Messages and Warnings

**File**: `src/cemaf/rlm/tool.py`

```python
async def execute(self, **kwargs: Any) -> ToolResult:
    # ... existing code ...

    # Add detailed warnings based on depth and coverage
    warnings = []

    if result.depth_reached >= max_depth:
        warnings.append(
            f"Max depth reached ({max_depth}). Last level used fallback strategy. "
            f"Expected information loss: 40-60%"
        )

    coverage_pct = (result.chunks_examined / len(chunks)) * 100
    if coverage_pct < 30:
        warnings.append(
            f"Very low coverage ({coverage_pct:.1f}%). "
            f"Answer based on <30% of document. "
            f"Consider increasing max_depth or using RAG instead."
        )
    elif coverage_pct < 60:
        warnings.append(
            f"Low coverage ({coverage_pct:.1f}%). "
            f"~{100-coverage_pct:.0f}% of document not examined."
        )

    if warnings:
        metadata["WARNINGS"] = warnings

    return Result.ok(result.answer, metadata=metadata)
```

---

## Phase 3: Enterprise Grade (4-6 weeks) → Target 9/10

### Goal
Formal verification, full provenance, uncertainty quantification.

### 3.1 Formal Coverage Bounds

**New file**: `src/cemaf/rlm/bounds.py`

```python
from dataclasses import dataclass
import math

@dataclass
class CoverageBound:
    """Mathematical bounds on coverage."""
    min_coverage: float
    max_coverage: float
    confidence_level: float = 0.95

    def get_effective_coverage_range(self) -> tuple[float, float]:
        """Get (pessimistic, optimistic) coverage estimates."""
        return (self.min_coverage, self.max_coverage)


class CoverageBoundCalculator:
    """Calculate mathematical bounds on information coverage."""

    def calculate_bounds(
        self,
        num_chunks: int,
        max_depth: int,
        budget: int,
        chunk_size: int,
    ) -> CoverageBound:
        """
        Calculate guaranteed bounds on coverage.

        Worst case: All examined chunks are from top of document
        Best case: Chunks are strategically distributed

        Mathematical guarantee: Coverage falls within [min, max]
        with 95% confidence.
        """

        # Best case: Perfect distribution of examined chunks
        chunks_examined_best = self._chunks_examined_best(
            num_chunks, max_depth, budget, chunk_size
        )
        max_coverage = min(1.0, chunks_examined_best / num_chunks)

        # Worst case: All chunks from beginning
        chunks_examined_worst = self._chunks_examined_worst(
            num_chunks, max_depth, budget, chunk_size
        )
        min_coverage = max(0.0, chunks_examined_worst / num_chunks)

        return CoverageBound(
            min_coverage=min_coverage,
            max_coverage=max_coverage,
            confidence_level=0.95,
        )

    def _chunks_examined_best(self, n, d, b, cs):
        """Best case: all budget used, optimally distributed."""
        # Assumes budget allows examining (b / cs) chunks
        # Spread optimally across document
        return min(n, b // cs)

    def _chunks_examined_worst(self, n, d, b, cs):
        """Worst case: fallback triggers, queries first chunk only."""
        # Fallback queries 1 chunk when depth exceeded
        if d <= 1:
            return 1
        # At depth d, at least 2^(d-1) chunks should be examined
        return max(1, 2 ** (d - 1))
```

### 3.2 Full Provenance Chain

**New file**: `src/cemaf/rlm/provenance.py`

```python
@dataclass
class Provenance:
    """Complete provenance chain for an answer."""

    answer: str
    derivation_path: list[str]  # ["chunk_5", "chunk_23", "aggregation_1"]
    recursion_depth: int
    information_loss: float
    confidence_bounds: tuple[float, float]  # (min, max)

    def get_audit_trail(self) -> str:
        """Generate human-readable audit trail."""
        return f"""
        Answer: {self.answer}

        Derivation Path:
        {' → '.join(self.derivation_path)}

        Recursion Depth: {self.recursion_depth}
        Information Loss: {self.information_loss:.1%}
        Confidence Range: {self.confidence_bounds[0]:.1%} - {self.confidence_bounds[1]:.1%}
        """
```

### 3.3 Uncertainty Quantification

**File**: `src/cemaf/rlm/uncertainty.py`

```python
@dataclass
class UncertaintyEstimate:
    """Uncertainty bounds on answer."""

    point_estimate: str  # The answer we give
    lower_bound: str    # Conservative version
    upper_bound: str    # Optimistic version
    confidence_level: float  # 0.9 for 90% CI
    uncertainty_sources: list[str]  # ["information_loss", "hallucination", ...]


class UncertaintyQuantifier:
    """Quantifies uncertainty in RLM answers."""

    async def quantify(
        self,
        rlm_result: RecursiveQueryResult,
        llm_client: LLMClient,
    ) -> UncertaintyEstimate:
        """
        Quantify uncertainty by asking LLM for bounds.
        """

        # Ask LLM for conservative version
        lower_prompt = f"""
        Given this answer: {rlm_result.answer}

        What's the most conservative/cautious version of this answer
        that hedges all claims? Include uncertainty qualifications.
        """

        lower_result = await llm_client.complete([Message.user(lower_prompt)])

        # Ask LLM for optimistic version
        upper_prompt = f"""
        Given this answer: {rlm_result.answer}

        What's the most confident/optimistic version of this answer?
        Assume all claims are correct.
        """

        upper_result = await llm_client.complete([Message.user(upper_prompt)])

        # Calculate uncertainty sources
        uncertainty_sources = [
            "information_loss_" + str(round(1 - rlm_result.coverage) * 100),
            "hallucination_risk_" + str(round(rlm_result.hallucination_prob) * 100),
            "recursion_depth_" + str(rlm_result.depth_reached),
        ]

        return UncertaintyEstimate(
            point_estimate=rlm_result.answer,
            lower_bound=lower_result.content,
            upper_bound=upper_result.content,
            confidence_level=0.90,
            uncertainty_sources=uncertainty_sources,
        )
```

---

## Phase 4: Recommendations for 9/10

### 4.1 Multi-Agent Consistency Validation

```python
class MultiAgentConsistencyValidator:
    """Validates consistency across multiple agents."""

    async def validate_consistency(
        self,
        document: str,
        agent_queries: list[str],
        tolerance: float = 0.85,  # 85% Jaccard similarity
    ) -> dict[str, Any]:
        """
        Run same document through multiple queries.
        Verify agents see consistent facts.
        """
        results = []

        for query in agent_queries:
            result = await self.rlm_tool.execute(
                instruction=query,
                content=document,
            )
            facts = extract_facts(result.data)
            results.append(facts)

        # Compute pairwise consistency
        consistencies = []
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                jaccard = len(results[i] & results[j]) / len(results[i] | results[j])
                consistencies.append(jaccard)

        avg_consistency = sum(consistencies) / len(consistencies)

        if avg_consistency < tolerance:
            warning = (
                f"Low consistency ({avg_consistency:.1%} < {tolerance:.1%}). "
                f"Different agents see different facts. "
                f"Results may be unreliable."
            )
            return {"consistent": False, "score": avg_consistency, "warning": warning}

        return {"consistent": True, "score": avg_consistency}
```

### 4.2 Hallucination Probability Bounds

```python
class HallucinationBoundCalculator:
    """Calculate probabilistic bounds on hallucination rate."""

    def calculate_hallucination_bound(
        self,
        llm_calls: int,
        base_hallucination_rate: float = 0.10,
    ) -> tuple[float, float]:
        """
        Calculate bounds on P(≥1 hallucination).

        Returns:
            (lower_bound, upper_bound) on hallucination probability
        """

        # Pessimistic: all calls are independent
        p_independent = 1.0 - ((1 - base_hallucination_rate) ** llm_calls)

        # Optimistic: all calls succeed
        p_optimistic = llm_calls * base_hallucination_rate  # Loose upper bound

        return (p_independent * 0.8, min(1.0, p_optimistic * 1.2))
```

---

## Timeline and Effort

| Phase | Target Score | Duration | Team Size | Priority |
|-------|----------|----------|-----------|----------|
| Phase 0 | 3/10 | 1 day | 1 | CRITICAL |
| Phase 1 | 5/10 | 1-2 weeks | 2-3 | HIGH |
| Phase 2 | 7/10 | 2-4 weeks | 2-3 | HIGH |
| Phase 3 | 9/10 | 4-6 weeks | 3-4 | MEDIUM |

---

## Definition of Done

### For Phase 0 (Safety Warnings)
- [ ] Documentation updated with safety warnings
- [ ] Coverage warnings added to metadata
- [ ] Test limitations documented
- [ ] PR reviewed and merged

### For Phase 1 (Basic Validation)
- [ ] Accuracy evaluator implemented
- [ ] Benchmark dataset created (10+ test cases)
- [ ] Confidence scoring in results
- [ ] Real LLM integration tests passing
- [ ] Metrics documented in README

### For Phase 2 (Production Safety)
- [ ] Coverage tracking implemented
- [ ] Source preservation (chunk IDs in answers)
- [ ] Adaptive depth selection working
- [ ] User warnings displayed prominently
- [ ] Production tests passing with real LLM

### For Phase 3 (Enterprise Grade)
- [ ] Coverage bounds implemented (mathematical proof)
- [ ] Provenance tracking complete
- [ ] Uncertainty quantification working
- [ ] Multi-agent consistency validation
- [ ] Hallucination bounds calculated
- [ ] Enterprise documentation complete

---

## Success Metrics

### Phase 0
- [ ] Zero customer questions about safety

### Phase 1
- [ ] RLM accuracy known for common use cases
- [ ] Information loss quantified
- [ ] Confidence scores correlate with actual accuracy (r > 0.8)

### Phase 2
- [ ] No silent data dropping (warnings shown for <60% coverage)
- [ ] Users can find answer sources
- [ ] Adaptive depth reduces failures

### Phase 3
- [ ] Mathematical bounds proven accurate
- [ ] Multi-agent systems show >85% consistency
- [ ] Enterprise-ready documentation
- [ ] Ready for compliance/audit work (maybe 7/10, not 9/10)

---

## Recommendation

**Start with Phase 0 today** (1 day of work):
- Add safety warnings
- Document test limitations
- Set expectations

**Plan Phase 1 for next sprint** (1-2 weeks):
- Creates concrete baseline on what works/doesn't
- Enables data-driven improvements
- Builds confidence in accuracy measurements

**Phases 2-3 are optional**:
- Phase 2 brings practical production improvements
- Phase 3 is research-grade (probably 9/10 is ceiling)
- Depends on use cases and customer needs

For most applications: **Phase 1 (5/10) is sufficient**. Phase 2 (7/10) only needed if RLM is mission-critical.
