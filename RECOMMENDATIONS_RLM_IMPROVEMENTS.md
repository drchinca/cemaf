# RLM Implementation Improvements: Concrete Recommendations

**Target:** Production-grade accuracy and safety for recursive context querying
**Priority:** Critical improvements for safe operation

---

## 1. Hallucination Detection & Prevention

### 1.1 Self-Consistency Checking

**Problem:** Single LLM call per chunk can hallucinate.

**Solution:** Query each chunk multiple times, check agreement.

```python
# Add to engine.py

class DivideAndConquerQueryEngineWithConsistency(DivideAndConquerQueryEngine):
    """Query engine with self-consistency checking."""

    async def _single_query(
        self,
        instruction: str,
        chunks: tuple[ContextChunk, ...],
        compiled: CompiledContext,
        consistency_runs: int = 3,  # Run each query 3 times
    ) -> dict[str, Any]:
        """Execute query with self-consistency checking."""

        # Run query multiple times
        responses = []
        for _ in range(consistency_runs):
            result = await self._query_once(instruction, chunks, compiled)
            if result["found"]:
                responses.append(result["answer"])

        if not responses:
            return {
                "answer": "No consistent findings",
                "found": False,
                "tokens_used": 0,
                "consistency_score": 0.0,
            }

        # Check consistency
        consistency_score = self._measure_consistency(responses)

        # Use most consistent response or synthesize if divergent
        if consistency_score > 0.8:
            # Responses are consistent - use first
            final_answer = responses[0]
        else:
            # Responses diverge - synthesize
            final_answer = await self._synthesize_inconsistent(
                instruction, responses
            )

        return {
            "answer": final_answer,
            "found": True,
            "tokens_used": 0,  # Would track actual usage
            "consistency_score": consistency_score,
            "num_responses": len(responses),
        }

    def _measure_consistency(self, responses: list[str]) -> float:
        """Measure how consistent responses are (0-1)."""
        if len(responses) < 2:
            return 1.0

        # Simple: BLEU score between pairs
        from nltk.translate.bleu_score import sentence_bleu

        scores = []
        reference = responses[0].split()
        for response in responses[1:]:
            hypothesis = response.split()
            score = sentence_bleu([reference], hypothesis, weights=(0.25, 0.25, 0.25, 0.25))
            scores.append(score)

        return sum(scores) / len(scores) if scores else 1.0

    async def _synthesize_inconsistent(
        self,
        instruction: str,
        responses: list[str],
    ) -> str:
        """When responses diverge, synthesize explaining divergence."""
        prompt = f"""
The same query was asked {len(responses)} times and received different answers:

Query: {instruction}

{chr(10).join(f"Response {i+1}: {r}" for i, r in enumerate(responses))}

The responses differ. This might indicate:
1. Genuine ambiguity in the source
2. LLM hallucination
3. Important nuances

Please synthesize these responses, noting:
- Where they agree (likely true)
- Where they disagree (uncertain)
- Confidence in the synthesis (0-100%)

Format your answer as:
AGREEMENT: [areas of agreement]
DISAGREEMENT: [areas where responses differ]
SYNTHESIS: [unified answer accounting for disagreements]
CONFIDENCE: [0-100%]
"""

        messages = [Message.user(prompt)]
        result = await self._llm.complete(messages)

        return result.content if result.success else "Synthesis failed"
```

### 1.2 Entailment Checking

**Problem:** LLM might invent logical connections between facts.

**Solution:** Verify answer is entailed by evidence.

```python
# Add to engine.py

class EntailmentChecker:
    """Check if answer is logically entailed by chunks."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def check_answer_grounding(
        self,
        answer: str,
        chunks: tuple[ContextChunk, ...],
        instruction: str,
    ) -> dict[str, Any]:
        """Check if answer is grounded in chunks."""

        prompt = f"""
Question: {instruction}

Proposed Answer: {answer}

Source Context:
{chr(10).join(f"[{c.chunk_id}] {c.content[:200]}..." for c in chunks[:5])}

Does the proposed answer logically follow from the source context?

For each claim in the answer:
1. Is it explicitly stated in the context? (yes/no)
2. Is it a reasonable inference? (yes/no)
3. Or is it potentially hallucinated? (yes/no)

Rate overall grounding: 0-100%

Format:
CLAIM: [specific claim from answer]
GROUNDED: [yes/no]
EVIDENCE: [quote from context, if exists]
CONFIDENCE: [0-100%]
"""

        result = await self._llm.complete([Message.user(prompt)])

        if not result.success:
            return {"grounded": False, "confidence": 0.0, "explanation": result.error}

        # Parse response to extract grounding percentage
        lines = result.content.split("\n")
        confidence_lines = [l for l in lines if l.startswith("CONFIDENCE")]

        confidence = 0.0
        if confidence_lines:
            try:
                confidence = float(confidence_lines[-1].split(":")[-1].strip().rstrip("%")) / 100
            except (ValueError, IndexError):
                confidence = 0.5

        return {
            "grounded": confidence > 0.7,
            "confidence": confidence,
            "explanation": result.content,
        }
```

### 1.3 Source Verification

**Problem:** Can't verify claims against original text.

**Solution:** Extract claims and verify against chunks.

```python
# Add to engine.py

class ClaimExtractor:
    """Extract verifiable claims from LLM output."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def extract_and_verify_claims(
        self,
        answer: str,
        chunks: tuple[ContextChunk, ...],
        instruction: str,
    ) -> dict[str, Any]:
        """Extract claims and verify against source."""

        # Step 1: Extract claims
        extraction_prompt = f"""
Answer: {answer}

Question: {instruction}

Extract all verifiable factual claims from this answer.

Format each claim as:
CLAIM: [specific claim]
CLAIM_TYPE: [factual/opinion/inference]
REQUIRED_EVIDENCE: [what would prove/disprove this]

List each claim on a new line.
"""

        result = await self._llm.complete([Message.user(extraction_prompt)])
        claims = self._parse_claims(result.content)

        # Step 2: Verify each claim
        verified_claims = []
        for claim in claims:
            verification = await self._verify_claim(claim, chunks)
            verified_claims.append({
                **claim,
                **verification,
            })

        # Step 3: Synthesize verification results
        total_claims = len(verified_claims)
        verified = sum(1 for c in verified_claims if c.get("verified", False))

        return {
            "claims": verified_claims,
            "total_claims": total_claims,
            "verified_claims": verified,
            "verification_rate": verified / total_claims if total_claims > 0 else 0.0,
            "overall_grounding": "strong" if verified / total_claims > 0.8 else "weak",
        }

    async def _verify_claim(
        self,
        claim: dict[str, str],
        chunks: tuple[ContextChunk, ...],
    ) -> dict[str, Any]:
        """Verify single claim against chunks."""

        verification_prompt = f"""
Claim: {claim.get('claim', '')}

Search the following context for evidence supporting or refuting this claim.

Context snippets:
{chr(10).join(f"[{c.chunk_id}] {c.content[:300]}" for c in chunks[:3])}

Evidence found: [quote if found, or "NOT FOUND"]
Verification: [YES/NO/PARTIAL]
Confidence: [0-100%]
Notes: [any relevant observations]
"""

        result = await self._llm.complete([Message.user(verification_prompt)])

        return {
            "verification_response": result.content,
            "verified": "YES" in result.content.upper(),
        }

    def _parse_claims(self, response: str) -> list[dict[str, str]]:
        """Parse claims from extraction response."""
        claims = []
        current_claim = {}

        for line in response.split("\n"):
            if line.startswith("CLAIM:"):
                if current_claim:
                    claims.append(current_claim)
                current_claim = {"claim": line.replace("CLAIM:", "").strip()}
            elif line.startswith("CLAIM_TYPE:"):
                current_claim["type"] = line.replace("CLAIM_TYPE:", "").strip()
            elif line.startswith("REQUIRED_EVIDENCE:"):
                current_claim["evidence_required"] = line.replace("REQUIRED_EVIDENCE:", "").strip()

        if current_claim:
            claims.append(current_claim)

        return claims
```

---

## 2. Confidence Scoring Throughout the Pipeline

### 2.1 Query-Level Confidence

**Modify single query to return confidence:**

```python
# Update _single_query in engine.py

async def _single_query(
    self,
    instruction: str,
    chunks: tuple[ContextChunk, ...],
    compiled: CompiledContext,
) -> dict[str, Any]:
    """Execute query with confidence scoring."""

    context_content = "\n\n---\n\n".join(
        f"[Chunk {chunk.chunk_id}]\n{chunk.content}"
        for chunk in chunks
    )

    prompt = f"""{instruction}

Context:
{context_content}

Provide your answer based on the context above. Include:
1. Your answer
2. How confident you are (0-100%)
3. Which chunks are most relevant
4. Any uncertainties or caveats

Format:
ANSWER: [your answer]
CONFIDENCE: [0-100%]
RELEVANT_CHUNKS: [chunk_ids separated by comma]
UNCERTAINTIES: [any caveats or uncertain parts]
"""

    messages = [Message.user(prompt)]
    result = await self._llm.complete(messages)

    if not result.success:
        return {
            "answer": f"Error: {result.error}",
            "found": False,
            "tokens_used": 0,
            "confidence": 0.0,
            "relevant_chunks": [],
        }

    # Parse structured response
    content = result.content if isinstance(result.content, str) else str(result.content)
    parsed = self._parse_structured_response(content)

    return {
        "answer": parsed.get("answer", content),
        "found": True,
        "tokens_used": int(result.total_tokens),
        "confidence": parsed.get("confidence", 0.5),
        "relevant_chunks": parsed.get("relevant_chunks", []),
        "uncertainties": parsed.get("uncertainties", ""),
    }

def _parse_structured_response(self, response: str) -> dict[str, Any]:
    """Parse structured LLM response."""
    result = {
        "answer": "",
        "confidence": 0.5,
        "relevant_chunks": [],
        "uncertainties": "",
    }

    for line in response.split("\n"):
        if line.startswith("ANSWER:"):
            result["answer"] = line.replace("ANSWER:", "").strip()
        elif line.startswith("CONFIDENCE:"):
            try:
                conf_str = line.replace("CONFIDENCE:", "").strip().rstrip("%")
                result["confidence"] = int(conf_str) / 100
            except (ValueError, IndexError):
                result["confidence"] = 0.5
        elif line.startswith("RELEVANT_CHUNKS:"):
            chunks = line.replace("RELEVANT_CHUNKS:", "").strip().split(",")
            result["relevant_chunks"] = [c.strip() for c in chunks if c.strip()]
        elif line.startswith("UNCERTAINTIES:"):
            result["uncertainties"] = line.replace("UNCERTAINTIES:", "").strip()

    return result
```

### 2.2 Propagate Confidence Through Aggregation

**Aggregate with confidence weighting:**

```python
# Update _aggregate_results in engine.py

async def _aggregate_results(
    self,
    instruction: str,
    left_result: RecursiveQueryResult,
    right_result: RecursiveQueryResult,
    budget: TokenBudget,
) -> dict[str, Any]:
    """Aggregate results with confidence propagation."""

    left_answer = left_result.answer or "No information found"
    right_answer = right_result.answer or "No information found"

    # Extract confidence from metadata
    left_confidence = left_result.metadata.get("confidence", 0.5)
    right_confidence = right_result.metadata.get("confidence", 0.5)

    prompt = f"""{instruction}

I have gathered information from two parts of the context:

Part 1 (Confidence: {left_confidence*100:.0f}%):
{left_answer}

Part 2 (Confidence: {right_confidence*100:.0f}%):
{right_answer}

Please synthesize these answers into a single, coherent response.

Consider:
1. Areas where both parts agree (likely high confidence)
2. Areas where they conflict (lower confidence)
3. Unique information in each part
4. Overall confidence in the synthesis

Format:
SYNTHESIS: [unified answer]
CONFIDENCE: [0-100%]
AGREEMENT: [what both parts agree on]
DISAGREEMENT: [what they conflict on]
UNIQUE_LEFT: [unique info from part 1]
UNIQUE_RIGHT: [unique info from part 2]
"""

    messages = [Message.user(prompt)]
    result = await self._llm.complete(messages)

    if not result.success:
        partial_info = f"{left_answer}; {right_answer}"
        # Combine confidences: geometric mean
        combined_confidence = (left_confidence * right_confidence) ** 0.5

        return {
            "answer": f"Aggregation failed: {result.error}. Partial results: {partial_info}",
            "tokens_used": 0,
            "confidence": combined_confidence * 0.5,  # Reduce for error
        }

    parsed = self._parse_aggregation_response(result.content)

    # Confidence: average of parts, adjusted for synthesis uncertainty
    synthesis_confidence = (left_confidence + right_confidence) / 2
    if parsed.get("confidence"):
        synthesis_confidence = (synthesis_confidence + parsed["confidence"]) / 2

    return {
        "answer": parsed.get("synthesis", result.content),
        "tokens_used": int(result.total_tokens),
        "confidence": synthesis_confidence,
        "agreement": parsed.get("agreement", ""),
        "disagreement": parsed.get("disagreement", ""),
    }

def _parse_aggregation_response(self, response: str) -> dict[str, Any]:
    """Parse aggregation response."""
    result = {
        "synthesis": "",
        "confidence": 0.5,
        "agreement": "",
        "disagreement": "",
    }

    for line in response.split("\n"):
        if line.startswith("SYNTHESIS:"):
            result["synthesis"] = line.replace("SYNTHESIS:", "").strip()
        elif line.startswith("CONFIDENCE:"):
            try:
                conf = line.replace("CONFIDENCE:", "").strip().rstrip("%")
                result["confidence"] = int(conf) / 100
            except (ValueError, IndexError):
                result["confidence"] = 0.5
        elif line.startswith("AGREEMENT:"):
            result["agreement"] = line.replace("AGREEMENT:", "").strip()
        elif line.startswith("DISAGREEMENT:"):
            result["disagreement"] = line.replace("DISAGREEMENT:", "").strip()

    return result
```

---

## 3. Grounding with Citations

### 3.1 Modify LLM Prompts for Citation

**Change query prompt to require citations:**

```python
# In engine.py: Update _single_query prompt

prompt = f"""{instruction}

Context:
{context_content}

Provide your answer with evidence from the context.

For each claim in your answer:
1. Make the claim
2. Cite which chunk(s) support it
3. Provide the exact quote if possible

Format your answer as:

ANSWER:
[Your main answer here]

EVIDENCE:
- Claim: [specific claim]
  Source: [chunk_ids that support it]
  Quote: "[exact quote from chunk]"

- Claim: [another claim]
  Source: [chunk_id]
  Quote: "[quote]"

UNCERTAIN_PARTS:
[Any parts without clear evidence]"""
```

### 3.2 Extract and Validate Citations

```python
# Add to engine.py

class CitationValidator:
    """Validate that citations actually support claims."""

    async def validate_citations(
        self,
        answer: str,
        chunks: tuple[ContextChunk, ...],
    ) -> dict[str, Any]:
        """Validate that claims are supported by citations."""

        # Parse citations from answer
        citations = self._extract_citations(answer)

        # Validate each citation
        validated = []
        for citation in citations:
            validation = await self._validate_single_citation(citation, chunks)
            validated.append({
                **citation,
                **validation,
            })

        # Summary
        valid_citations = sum(1 for c in validated if c.get("valid", False))
        total_citations = len(validated)

        return {
            "citations": validated,
            "valid_count": valid_citations,
            "total_count": total_citations,
            "citation_accuracy": valid_citations / total_citations if total_citations > 0 else 0,
            "answer_is_grounded": valid_citations / total_citations > 0.8 if total_citations > 0 else False,
        }

    def _extract_citations(self, answer: str) -> list[dict[str, Any]]:
        """Extract citations from structured answer."""
        citations = []

        in_evidence = False
        for line in answer.split("\n"):
            if line.startswith("EVIDENCE:"):
                in_evidence = True
                continue
            if line.startswith("UNCERTAIN_PARTS:"):
                in_evidence = False
                continue

            if in_evidence and line.strip().startswith("- Claim:"):
                # Parse citation entry
                citation = {"claim": "", "source_chunks": [], "quote": ""}
                # Would parse the structured format here
                citations.append(citation)

        return citations

    async def _validate_single_citation(
        self,
        citation: dict[str, Any],
        chunks: tuple[ContextChunk, ...],
    ) -> dict[str, Any]:
        """Validate a single citation."""

        claimed_chunks = citation.get("source_chunks", [])
        quote = citation.get("quote", "")

        # Check if quote appears in claimed chunks
        found = False
        for chunk_id in claimed_chunks:
            chunk = next((c for c in chunks if c.chunk_id == chunk_id), None)
            if chunk and quote in chunk.content:
                found = True
                break

        return {
            "valid": found,
            "quote_found": found,
            "chunks_exist": all(
                any(c.chunk_id == cid for c in chunks)
                for cid in claimed_chunks
            ),
        }
```

---

## 4. Information Preservation Metrics

### 4.1 Track Content Coverage

```python
# Add to engine.py or create new module

class InformationPreservationTracker:
    """Track how much of original content makes it to final answer."""

    def __init__(self, estimator: TokenEstimator):
        self._estimator = estimator

    async def measure_preservation(
        self,
        original_chunks: tuple[ContextChunk, ...],
        examined_chunks: tuple[ContextChunk, ...],
        final_answer: str,
        instruction: str,
    ) -> dict[str, Any]:
        """Measure information preservation through the pipeline."""

        total_tokens = sum(int(c.token_count) for c in original_chunks)
        examined_tokens = sum(int(c.token_count) for c in examined_chunks)
        answer_tokens = self._estimator.estimate(final_answer)

        # Calculate metrics
        coverage_percent = (examined_tokens / total_tokens * 100) if total_tokens > 0 else 0
        information_density = answer_tokens / examined_tokens if examined_tokens > 0 else 0

        # Check what topics were covered
        topics_in_original = self._extract_topics(original_chunks)
        topics_in_answer = self._extract_topics([
            type('Chunk', (), {'content': final_answer})()
        ])

        topic_coverage = len(topics_in_answer & topics_in_original) / len(topics_in_original) if topics_in_original else 0

        return {
            "total_tokens": total_tokens,
            "examined_tokens": examined_tokens,
            "answer_tokens": answer_tokens,
            "coverage_percent": coverage_percent,
            "information_density": information_density,  # Answer tokens / examined tokens
            "topic_coverage": topic_coverage,
            "preservation_estimate": (coverage_percent / 100) * 0.8,  # 80% of covered = preserved
        }

    def _extract_topics(self, chunks) -> set:
        """Extract key topics/entities from chunks."""
        # Simplified: would use NLP for production
        topics = set()
        for chunk in chunks:
            # Extract capitalized phrases (entities)
            import re
            entities = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', chunk.content)
            topics.update(entities)
        return topics
```

### 4.2 Add Information Loss Tracking

```python
# Modify RecursiveQueryResult to include preservation metrics

@dataclass(frozen=True)
class RecursiveQueryResult:
    # ... existing fields ...

    # New fields for ML observability
    information_preservation: float = 1.0  # 0-1: % of info preserved
    coverage_percent: float = 100.0        # 0-100: % of content examined
    confidence_overall: float = 0.5         # 0-1: overall confidence
    grounding_score: float = 0.0           # 0-1: how grounded is answer?
    hallucination_risk: float = 0.5        # 0-1: estimated hallucination risk
```

---

## 5. Semantic Chunking with Overlap

### 5.1 Implement Overlapping Chunks

```python
# Add to chunking.py

class OverlappingChunkingStrategy:
    """Chunking strategy with overlap for better coherence."""

    def __init__(
        self,
        token_estimator: TokenEstimator,
        chunk_size: int = 500,
        overlap_percent: int = 15,  # 15% overlap
    ) -> None:
        self._estimator = token_estimator
        self._chunk_size = chunk_size
        self._overlap_percent = overlap_percent

    def chunk(
        self,
        content: str,
        max_chunk_tokens: int,
    ) -> tuple[ContextChunk, ...]:
        """Chunk content with overlap between chunks."""

        base_strategy = FixedSizeChunkingStrategy(self._estimator, self._chunk_size)
        base_chunks = base_strategy.chunk(content, max_chunk_tokens)

        if len(base_chunks) <= 1:
            return base_chunks

        # Add overlap between consecutive chunks
        overlap_tokens = int((self._chunk_size * self._overlap_percent) / 100)
        overlapped_chunks = []

        for i, chunk in enumerate(base_chunks):
            if i == 0:
                # First chunk: no previous context
                overlapped_chunks.append(chunk)
            else:
                # Add context from previous chunk
                prev_chunk = base_chunks[i - 1]

                # Take end of previous chunk as context
                prev_content = prev_chunk.content
                prev_words = prev_content.split()

                # Estimate words to include for overlap_tokens
                words_per_token = len(prev_words) / int(prev_chunk.token_count)
                overlap_words = int(overlap_tokens * words_per_token)

                # Create overlapped content
                overlap_text = " ".join(prev_words[-overlap_words:])
                new_content = overlap_text + "\n\n" + chunk.content

                # Create new chunk with overlap
                new_chunk = ContextChunk(
                    chunk_id=chunk.chunk_id,
                    content=new_content,
                    token_count=TokenCount(
                        int(chunk.token_count) + overlap_tokens
                    ),
                    parent_id=chunk.parent_id,
                    depth=chunk.depth,
                    metadata={
                        **chunk.metadata,
                        "has_overlap": True,
                        "overlap_tokens": overlap_tokens,
                    },
                )
                overlapped_chunks.append(new_chunk)

        return tuple(overlapped_chunks)
```

### 5.2 Semantic Boundary Detection

```python
# Add to chunking.py

class SemanticBoundaryDetector:
    """Detect semantic boundaries for better chunking."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def detect_boundaries(self, content: str) -> list[int]:
        """Detect likely semantic boundaries (section breaks, etc)."""

        # Use simple heuristics first
        boundaries = []

        lines = content.split("\n")
        for i, line in enumerate(lines):
            # Detect heading patterns
            if line.startswith("#") or line.startswith("==") or line.startswith("--"):
                boundaries.append(i)

            # Detect section breaks (blank lines)
            if not line.strip() and i > 0 and i < len(lines) - 1:
                if lines[i-1].strip() and lines[i+1].strip():
                    boundaries.append(i)

        # For complex content, could use LLM to identify semantic units
        # (not implemented here due to cost)

        return sorted(set(boundaries))

    def chunk_on_boundaries(
        self,
        content: str,
        boundaries: list[int],
        max_chunk_tokens: int,
    ) -> tuple[ContextChunk, ...]:
        """Chunk respecting semantic boundaries."""

        lines = content.split("\n")
        chunks = []
        current_chunk = []
        current_tokens = 0
        chunk_id = 0

        for line_idx, line in enumerate(lines):
            line_tokens = len(line.split())  # Rough estimate

            # Check if we've hit a boundary
            is_boundary = line_idx in boundaries

            if current_tokens + line_tokens > max_chunk_tokens and current_chunk:
                # Flush current chunk
                chunk_text = "\n".join(current_chunk)
                chunks.append(
                    ContextChunk(
                        chunk_id=f"chunk_{chunk_id}",
                        content=chunk_text,
                        token_count=TokenCount(current_tokens),
                        metadata={"type": "semantic_chunk"},
                    )
                )
                chunk_id += 1
                current_chunk = []
                current_tokens = 0

            current_chunk.append(line)
            current_tokens += line_tokens

            # Force chunk boundary at semantic boundaries if we have content
            if is_boundary and current_chunk:
                chunk_text = "\n".join(current_chunk)
                chunks.append(
                    ContextChunk(
                        chunk_id=f"chunk_{chunk_id}",
                        content=chunk_text,
                        token_count=TokenCount(current_tokens),
                        metadata={"type": "semantic_chunk", "boundary": True},
                    )
                )
                chunk_id += 1
                current_chunk = []
                current_tokens = 0

        # Flush remaining
        if current_chunk:
            chunk_text = "\n".join(current_chunk)
            chunks.append(
                ContextChunk(
                    chunk_id=f"chunk_{chunk_id}",
                    content=chunk_text,
                    token_count=TokenCount(current_tokens),
                    metadata={"type": "semantic_chunk"},
                )
            )

        return tuple(chunks)
```

---

## 6. Evaluation Framework

### 6.1 Accuracy Benchmarking

```python
# Add tests/evaluation/test_rlm_accuracy.py

import pytest
from typing import Callable

class RLMAccuracyEvaluator:
    """Evaluate RLM accuracy against ground truth."""

    def __init__(self, rlm_tool, llm_client):
        self._rlm = rlm_tool
        self._llm = llm_client

    async def evaluate_on_dataset(
        self,
        dataset: list[dict],  # Each item: {question, context, answer}
    ) -> dict:
        """Evaluate RLM on dataset."""

        results = []
        for item in dataset:
            result = await self._evaluate_single(item)
            results.append(result)

        return self._summarize_results(results)

    async def _evaluate_single(self, item: dict) -> dict:
        """Evaluate single item."""

        result = await self._rlm.execute(
            instruction=item["question"],
            content=item["context"],
        )

        if not result.success:
            return {
                "question": item["question"],
                "exact_match": False,
                "f1_score": 0.0,
                "bleu_score": 0.0,
                "error": result.error,
            }

        # Calculate metrics
        exact_match = result.data.strip().lower() == item["answer"].strip().lower()
        f1_score = self._calculate_f1(result.data, item["answer"])
        bleu_score = self._calculate_bleu(result.data, item["answer"])

        return {
            "question": item["question"],
            "expected": item["answer"],
            "actual": result.data,
            "exact_match": exact_match,
            "f1_score": f1_score,
            "bleu_score": bleu_score,
            "metadata": result.metadata,
        }

    def _calculate_f1(self, predicted: str, expected: str) -> float:
        """Calculate F1 score between predicted and expected."""
        pred_tokens = set(predicted.lower().split())
        exp_tokens = set(expected.lower().split())

        if not exp_tokens:
            return 1.0 if not pred_tokens else 0.0

        overlap = pred_tokens & exp_tokens
        precision = len(overlap) / len(pred_tokens) if pred_tokens else 0
        recall = len(overlap) / len(exp_tokens)

        if precision + recall == 0:
            return 0.0

        return 2 * (precision * recall) / (precision + recall)

    def _calculate_bleu(self, predicted: str, expected: str) -> float:
        """Calculate BLEU score."""
        from nltk.translate.bleu_score import sentence_bleu

        reference = expected.lower().split()
        hypothesis = predicted.lower().split()

        return sentence_bleu([reference], hypothesis, weights=(0.25, 0.25, 0.25, 0.25))

    def _summarize_results(self, results: list[dict]) -> dict:
        """Summarize evaluation results."""

        n = len(results)
        exact_matches = sum(1 for r in results if r.get("exact_match", False))
        avg_f1 = sum(r.get("f1_score", 0) for r in results) / n if n > 0 else 0
        avg_bleu = sum(r.get("bleu_score", 0) for r in results) / n if n > 0 else 0

        return {
            "total_items": n,
            "exact_match_rate": exact_matches / n if n > 0 else 0,
            "avg_f1": avg_f1,
            "avg_bleu": avg_bleu,
            "results": results,
        }

@pytest.mark.asyncio
async def test_rlm_accuracy_on_benchmark(rlm_tool):
    """Test RLM accuracy on standard benchmark."""

    # Example dataset (would be larger in practice)
    dataset = [
        {
            "question": "What is the capital of France?",
            "context": "France is a country in Europe. The capital of France is Paris.",
            "answer": "Paris",
        },
        # ... more items
    ]

    evaluator = RLMAccuracyEvaluator(rlm_tool, None)
    results = await evaluator.evaluate_on_dataset(dataset)

    # Assertions
    assert results["exact_match_rate"] >= 0.80, "Should achieve 80%+ exact match"
    assert results["avg_f1"] >= 0.85, "Should achieve 85%+ F1 score"
    assert results["avg_bleu"] >= 0.80, "Should achieve 80%+ BLEU score"
```

### 6.2 Hallucination Detection Testing

```python
# Add tests/evaluation/test_rlm_hallucination.py

class HallucinationDetector:
    """Detect hallucinations in RLM output."""

    def __init__(self, llm_client):
        self._llm = llm_client

    async def detect_hallucinations(
        self,
        answer: str,
        chunks: tuple[ContextChunk, ...],
    ) -> dict:
        """Detect and measure hallucinations."""

        hallucination_rate = await self._measure_grounding(answer, chunks)

        return {
            "hallucination_rate": hallucination_rate,
            "is_hallucinated": hallucination_rate > 0.15,
            "severity": "high" if hallucination_rate > 0.30 else "medium" if hallucination_rate > 0.15 else "low",
        }

    async def _measure_grounding(
        self,
        answer: str,
        chunks: tuple[ContextChunk, ...],
    ) -> float:
        """Measure % of claims not grounded in chunks."""

        prompt = f"""
Answer to evaluate: {answer}

Source context (first 3 chunks):
{chr(10).join(f"[{c.chunk_id}] {c.content[:200]}" for c in chunks[:3])}

For each distinct claim in the answer:
1. Is it explicitly mentioned in the source? (YES/NO)
2. Is it a reasonable inference? (YES/NO)
3. Or appears to be hallucinated? (YES/NO)

Rate: [X]% of claims appear hallucinated

Be conservative - count as hallucinated if not clearly grounded.
"""

        result = await self._llm.complete([Message.user(prompt)])

        # Extract hallucination percentage
        import re
        match = re.search(r'(\d+)%', result.content)
        if match:
            return int(match.group(1)) / 100

        return 0.5  # Default: uncertain

@pytest.mark.asyncio
async def test_hallucination_rate(rlm_tool):
    """Test that RLM has acceptable hallucination rate."""

    content = "AI is a technology. It processes data. It makes predictions."
    result = await rlm_tool.execute(
        instruction="What can AI do?",
        content=content,
    )

    detector = HallucinationDetector(None)
    hallucination_result = await detector.detect_hallucinations(
        result.data,
        tuple(),  # Would pass actual chunks
    )

    assert hallucination_result["hallucination_rate"] < 0.15, "Should have <15% hallucinations"
```

---

## Implementation Roadmap

### Phase 1 (Immediate - Week 1)
1. Add hallucination detection (self-consistency checking)
2. Add confidence scoring to all LLM calls
3. Update RecursiveQueryResult with new ML metrics

### Phase 2 (Short-term - Week 2-3)
4. Implement grounding with citations
5. Add information preservation tracking
6. Create evaluation framework

### Phase 3 (Medium-term - Week 4-5)
7. Implement semantic chunking with overlap
8. Add chain-of-thought to aggregation
9. Expand evaluation tests

### Phase 4 (Polish - Week 6)
10. Performance optimization
11. Documentation updates
12. Integration testing

---

**End of Recommendations**
