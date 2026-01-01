# Evaluations

Evaluators and LLM-as-judge for testing and validation.

## Evaluation Architecture

```mermaid
flowchart TB
    subgraph Evaluators
        EXACT[ExactMatchEvaluator<br/>Exact comparison]
        CONTAINS[ContainsEvaluator<br/>Substring check]
        SEMANTIC[SemanticEvaluator<br/>Meaning comparison]
    end

    subgraph LLM Judge
        JUDGE[LLMJudge<br/>AI evaluation]
        PROMPT[Evaluation Prompt<br/>Criteria]
        LLM[LLM Client<br/>Reasoning]
    end

    subgraph Results
        SCORE[Score<br/>0.0 - 1.0]
        FEEDBACK[Feedback<br/>Explanation]
    end

    EXACT --> SCORE
    CONTAINS --> SCORE
    SEMANTIC --> SCORE
    PROMPT --> JUDGE
    JUDGE --> LLM
    LLM --> SCORE
    LLM --> FEEDBACK
```

## Evaluation Flow

```mermaid
sequenceDiagram
    participant Test
    participant Evaluator
    participant Judge as LLMJudge
    participant LLM

    Note over Test,LLM: Simple Evaluation
    Test->>Evaluator: evaluate(expected, actual)
    Evaluator-->>Test: EvalResult(score, pass)

    Note over Test,LLM: LLM-as-Judge
    Test->>Judge: evaluate(prompt, response)
    Judge->>LLM: complete(eval_prompt)
    LLM-->>Judge: judgment
    Judge-->>Test: EvalResult(score, feedback)
```

## Evaluators

```python
from cemaf.evals.evaluators import ExactMatchEvaluator, ContainsEvaluator

# Exact match
evaluator = ExactMatchEvaluator()
result = evaluator.evaluate("expected", "actual")

# Contains
evaluator = ContainsEvaluator(substrings=["required"])
result = evaluator.evaluate("text with required content")
```

## LLM-as-Judge

```python
from cemaf.evals.llm_judge import LLMJudge

judge = LLMJudge(llm_client=my_llm)
result = await judge.evaluate(
    prompt="Is this correct?",
    response="The answer is 42"
)
```
