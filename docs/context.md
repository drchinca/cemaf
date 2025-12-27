# Context Management

CEMAF provides sophisticated context management with token budgeting, compilation, and automatic summarization.

## Context Class

Immutable context object for state management:

```python
from cemaf.context.context import Context

# Create context
ctx = Context(data={"key": "value"})

# Get values (supports dot notation)
value = ctx.get("key")
nested = ctx.get("data.user.id", default=None)

# Set values (returns new Context)
new_ctx = ctx.set("new_key", "new_value")
nested_ctx = ctx.set("data.user.id", 123)

# Merge contexts
merged = ctx1.merge(ctx2)

# Convert to dict
data = ctx.to_dict()
```

## Token Budget

Manage token limits for LLM context:

```python
from cemaf.context.budget import TokenBudget

# Create budget
budget = TokenBudget(max_tokens=1000, reserved_for_output=200)

# Available tokens for context
available = budget.available_tokens  # 800

# Model-specific budgets
budget = TokenBudget.for_model("gpt-4", reserved_for_output=200)
```

## Context Compiler

Compile context from artifacts and memories:

```python
from cemaf.context.compiler import PriorityContextCompiler

compiler = PriorityContextCompiler()

compiled = await compiler.compile(
    artifacts=(("brief", "important content"),),
    memories=(("mem1", "relevant memory"),),
    budget=TokenBudget(max_tokens=1000),
    priorities={"brief": 10, "mem1": 5}
)

# Check if within budget
if compiled.within_budget():
    messages = compiled.to_messages()
```

## Advanced Context Compiler

Automatically summarizes low-priority sources when budget is exceeded:

```python
from cemaf.context.advanced_compiler import AdvancedContextCompiler
from cemaf.context.budget import TokenBudget

compiler = AdvancedContextCompiler(
    llm_client=my_llm_client,
    token_estimator=my_estimator
)

budget = TokenBudget(max_tokens=1000, reserved_for_output=200)
compiled = await compiler.compile(
    artifacts=(("brief", "important content"),),
    memories=(("long_mem", "very long content..."),),
    budget=budget,
    priorities={"brief": 10, "long_mem": 0}  # long_mem will be summarized if needed
)
```

The `AdvancedContextCompiler`:
1. Gathers all sources first
2. Checks if total tokens exceed budget
3. Summarizes lowest-priority sources first
4. Continues until budget is met or all sources processed

## Token Estimation

Estimate tokens for content:

```python
from cemaf.context.compiler import SimpleTokenEstimator

estimator = SimpleTokenEstimator()
tokens = estimator.estimate("Hello world")  # ~2 tokens
```

