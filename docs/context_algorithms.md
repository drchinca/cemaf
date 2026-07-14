# Context Selection Algorithms

CEMAF ships context selection algorithms for deciding which `ContextSource`
objects fit within a `TokenBudget`. This page documents the implemented
surface in `cemaf.context.algorithm` and `cemaf.context.factories`.

The framework does not currently ship KV-cache management, semantic compression
pipelines, prefix pools, or local Llama.cpp clients. Those ideas require their
own protocols and tests before they become public CEMAF APIs.

## Overview

The `ContextSelectionAlgorithm` protocol enables pluggable selection strategies:

- **Greedy**: fast, includes highest-priority sources first.
- **Knapsack**: maximizes priority sum within the token budget.
- **Optimal**: brute-force optimal for small source sets, with a knapsack
  fallback for larger sets.
- **Custom**: any object that structurally implements `select_sources`.

## Protocol Interface

```python
from typing import Protocol, runtime_checkable

from cemaf.context.algorithm import SelectionResult
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource

@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        ...
```

## Built-In Algorithms

### GreedySelectionAlgorithm

Includes sources in priority order until the budget is exhausted.

```python
from cemaf.context.algorithm import GreedySelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=GreedySelectionAlgorithm(),
)
```

Use it when priorities are well-calibrated and speed matters more than global
optimality.

### KnapsackSelectionAlgorithm

Uses 0/1 knapsack dynamic programming to maximize priority sum within budget.

```python
from cemaf.context.algorithm import KnapsackSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=KnapsackSelectionAlgorithm(),
)
```

Use it when the budget is tight and priority maximization matters.

### OptimalSelectionAlgorithm

Uses brute force for small source sets and falls back to knapsack for larger
sets.

```python
from cemaf.context.algorithm import OptimalSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=OptimalSelectionAlgorithm(max_sources=20),
)
```

Use it for small, high-value context sets where exact optimality matters.

## Custom Algorithms

Custom algorithms only need to implement the protocol.

```python
from cemaf.context.algorithm import SelectionResult
from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource

class DiversitySelectionAlgorithm:
    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        selected: list[ContextSource] = []
        total_tokens = 0
        seen_types: set[str] = set()

        for source in sorted(sources, key=lambda s: s.priority, reverse=True):
            source_tokens = int(source.token_count or 0)
            if total_tokens + source_tokens > budget.available_tokens:
                continue
            if source.type in seen_types and len(selected) >= 3:
                continue
            selected.append(source)
            total_tokens += source_tokens
            seen_types.add(str(source.type))

        excluded_keys = [source.key for source in sources if source not in selected]
        return SelectionResult(
            selected_sources=tuple(selected),
            total_tokens=total_tokens,
            metadata={
                "selection_method": "diversity",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
            },
        )
```

## SelectionResult

`SelectionResult` contains:

- `selected_sources`: selected `ContextSource` objects.
- `total_tokens`: token count used by the selected set.
- `metadata`: algorithm-specific information.

Convenience properties expose `excluded_count`, `excluded_keys`, and
`selection_method` from metadata.

## Factory Functions

```python
from cemaf.context.factories import (
    create_greedy_compiler,
    create_knapsack_compiler,
    create_optimal_compiler,
)

greedy = create_greedy_compiler()
knapsack = create_knapsack_compiler()
optimal = create_optimal_compiler(max_sources=15)
```

## Algorithm Comparison

| Algorithm | Speed | Optimality | Best For |
|---|---|---|---|
| Greedy | Fast, O(n) | Approximate | General use, calibrated priorities |
| Knapsack | Medium, O(n x budget) | Optimal priority sum | Tight budgets |
| Optimal | Slow for small sets | Guaranteed for small sets | Small critical selections |

## Advanced Compiler Integration

`AdvancedContextCompiler` also accepts a selection algorithm before
summarization.

```python
from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.algorithm import KnapsackSelectionAlgorithm

compiler = AdvancedContextCompiler(
    llm_client=llm_client,
    token_estimator=estimator,
    algorithm=KnapsackSelectionAlgorithm(),
)
```

## Deferred Capabilities

The following capabilities are not public CEMAF APIs today:

- KV-cache managers and prefix-aware compilers.
- Shared prefix pools.
- Semantic or entity-preserving compression services.
- Llama.cpp-local LLM clients.

Keep these in consuming applications or external packages until a CEMAF spec
defines the protocol boundary and an integration test proves the behavior.
