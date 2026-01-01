# Context Selection Algorithms

CEMAF provides an extensible protocol for context selection algorithms, allowing engineers to implement custom strategies for choosing which sources to include within token budget constraints.

## Overview

The `ContextSelectionAlgorithm` protocol enables pluggable selection strategies:

- **Greedy**: Fast, includes highest priority sources first (default)
- **Knapsack**: Optimal priority maximization using dynamic programming
- **Optimal**: Guaranteed optimal solution for small sets
- **Custom**: Engineer-defined algorithms

## Protocol Interface

```python
@runtime_checkable
class ContextSelectionAlgorithm(Protocol):
    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        """
        Select sources that fit within token budget.

        Args:
            sources: All available context sources (may be pre-sorted)
            budget: Token budget constraints

        Returns:
            SelectionResult with selected sources and metadata
        """
        ...
```

## Built-in Algorithms

### GreedySelectionAlgorithm

**Strategy**: Includes highest priority sources first until budget exhausted.

**Characteristics**:
- Time Complexity: O(n)
- Space Complexity: O(n)
- Optimality: Not guaranteed - may miss better combinations
- Best For: Fast selection when priorities are well-calibrated

**Example**:
```python
from cemaf.context.algorithm import GreedySelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = GreedySelectionAlgorithm()
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

### KnapsackSelectionAlgorithm

**Strategy**: Uses 0/1 knapsack dynamic programming to maximize sum of priorities within budget.

**Characteristics**:
- Time Complexity: O(n × budget)
- Space Complexity: O(n × budget)
- Optimality: Optimal for 0/1 knapsack (maximizes priority sum)
- Best For: When you need optimal priority maximization

**Example**:
```python
from cemaf.context.algorithm import KnapsackSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = KnapsackSelectionAlgorithm()
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

**Note**: For very large budgets (>100K tokens), automatically falls back to greedy for performance.

### OptimalSelectionAlgorithm

**Strategy**: Uses brute force for small sets to find truly optimal solution, falls back to knapsack for larger sets.

**Characteristics**:
- Time Complexity: O(2^n) for brute force, O(n × budget) for fallback
- Space Complexity: O(2^n) for brute force
- Optimality: Guaranteed optimal for small sets (< 20 sources)
- Best For: Small sets where optimality is critical

**Example**:
```python
from cemaf.context.algorithm import OptimalSelectionAlgorithm
from cemaf.context.compiler import PriorityContextCompiler, SimpleTokenEstimator

algorithm = OptimalSelectionAlgorithm(max_sources=20)
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=algorithm,
)
```

## Implementing Custom Algorithms

To implement a custom algorithm, simply conform to the `ContextSelectionAlgorithm` protocol:

```python
from cemaf.context.algorithm import (
    ContextSelectionAlgorithm,
    SelectionResult,
)
from cemaf.context.compiler import ContextSource
from cemaf.context.budget import TokenBudget

class MyCustomAlgorithm:
    """Custom algorithm that prioritizes diversity."""

    def select_sources(
        self,
        sources: list[ContextSource],
        budget: TokenBudget,
    ) -> SelectionResult:
        selected: list[ContextSource] = []
        total_tokens = 0
        available_tokens = budget.available_tokens

        # Custom logic: prioritize diverse sources
        seen_types = set()
        for source in sorted(sources, key=lambda s: s.priority, reverse=True):
            if total_tokens + source.token_count <= available_tokens:
                # Prefer sources of different types
                if source.type not in seen_types or len(selected) < 3:
                    selected.append(source)
                    total_tokens += source.token_count
                    seen_types.add(source.type)

        excluded_keys = [s.key for s in sources if s not in selected]

        return SelectionResult(
            selected_sources=tuple(selected),
            total_tokens=total_tokens,
            metadata={
                "selection_method": "custom_diversity",
                "excluded_count": len(excluded_keys),
                "excluded_keys": excluded_keys,
            },
        )

# Use custom algorithm
compiler = PriorityContextCompiler(
    token_estimator=SimpleTokenEstimator(),
    algorithm=MyCustomAlgorithm(),
)
```

## SelectionResult

The `SelectionResult` dataclass contains:

- `selected_sources`: Tuple of selected `ContextSource` objects
- `total_tokens`: Total tokens used
- `metadata`: Algorithm-specific information (excluded count, method, etc.)

**Properties**:
- `excluded_count`: Number of excluded sources
- `excluded_keys`: Keys of excluded sources
- `selection_method`: Algorithm method name

## Factory Functions

CEMAF provides factory functions for common setups:

```python
from cemaf.context.factories import (
    create_greedy_compiler,
    create_knapsack_compiler,
    create_optimal_compiler,
)

# Greedy (default)
compiler = create_greedy_compiler()

# Knapsack
compiler = create_knapsack_compiler()

# Optimal
compiler = create_optimal_compiler(max_sources=15)
```

## Algorithm Comparison

| Algorithm | Speed | Optimality | Best For |
|-----------|-------|------------|----------|
| Greedy | Fast (O(n)) | Approximate | General use, well-calibrated priorities |
| Knapsack | Medium (O(n×budget)) | Optimal (priority sum) | Need optimal priority maximization |
| Optimal | Slow (O(2^n)) | Guaranteed optimal | Small sets (< 20 sources) |

## Best Practices

1. **Choose the right algorithm**: Greedy for speed, Knapsack for optimality, Optimal for small sets
2. **Calibrate priorities**: Ensure priorities accurately reflect importance
3. **Monitor metadata**: Check `SelectionResult.metadata` for algorithm insights
4. **Test custom algorithms**: Verify they respect budget constraints
5. **Consider performance**: For large budgets or many sources, prefer greedy

## Advanced Usage

### Using with AdvancedContextCompiler

The `AdvancedContextCompiler` also supports algorithm selection:

```python
from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.algorithm import KnapsackSelectionAlgorithm

compiler = AdvancedContextCompiler(
    llm_client=llm_client,
    token_estimator=estimator,
    algorithm=KnapsackSelectionAlgorithm(),  # Use knapsack before summarization
)
```

### Algorithm Metadata

Algorithms can provide metadata about their selection process:

```python
result = algorithm.select_sources(sources, budget)

# Access metadata
print(f"Method: {result.selection_method}")
print(f"Excluded: {result.excluded_count}")
print(f"Max priority sum: {result.metadata.get('max_priority_sum')}")
print(f"Guaranteed optimal: {result.metadata.get('guaranteed_optimal', False)}")
```

## Examples

See `cemaf/examples/retrieval_dag_example.py` for a complete example demonstrating:
- Using different algorithms
- Comparing results
- Showing algorithm metadata
- Custom algorithm implementation
