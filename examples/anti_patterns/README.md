# Anti-Patterns: Stop Before You Reimplement CEMAF

The most common failure when building on CEMAF is using 3–5 modules and then
re-inventing the rest in app code. Each anti-pattern below is something CEMAF
already owns. If you catch yourself writing the ❌ side, reach for the ✅ primitive.

See runnable best-practice examples in [`../byo/`](../byo) and [`../app_shapes/`](../app_shapes).

---

## 1. Rolling-prompt string as state

❌ Accumulating a growing prompt string and passing it turn to turn:

```python
prompt = system + "\n" + history + "\n" + new_turn  # unbounded, no provenance
```

✅ Use the immutable `Context` + `ContextPatch` — state is structured, auditable,
and token-budgeted.

```python
from cemaf.context import Context, ContextPatch
ctx = ctx.apply(ContextPatch.from_tool(tool_id="search", path="results", value=data))
```

---

## 2. Hand-rolled agent loop bypassing the executor

❌ Driving agents with your own control flow:

```python
while not done:
    out = await agent.run(goal)        # no retries, no events, no replay, no gates
    done = check(out)
```

✅ Declare the flow as a `DAG` and run it through `create_executor` — you get
retries, events, provenance, and conditional routing for free.

```python
from cemaf import DAG, Node, create_executor
dag = DAG(name="pipeline").add_node(node=Node.agent(id="step", name="Step", agent_id="MyAgent"))
run = await create_executor(agent_registry=registry).run(dag=dag)
```

---

## 3. Shared mutable dict as the state layer

❌ Threading a plain dict that every agent mutates:

```python
state = {}
state["x"] = compute()   # who wrote this? when? mutation races on concurrent nodes
```

✅ `Context` is immutable — every change returns a new context with provenance,
so concurrent nodes never clobber each other ([`../../src/cemaf/collision`](../../src/cemaf/collision)
coordinates writes).

```python
from cemaf.context import Context
new_ctx = ctx.set("x", value)   # original ctx untouched
```

---

## 4. Per-feature token / cost counter

❌ Counting tokens and dollars by hand in each agent:

```python
total_tokens += len(text) // 4
if total_cost > budget: raise RuntimeError("over budget")
```

✅ Wire `TokenBudget` + `BudgetGuard` once through `RuntimeServices`; every node
is metered automatically.

```python
from cemaf.context.budget import TokenBudget
from cemaf.observability.budget_guard import BudgetGuard
from cemaf.orchestration.services import RuntimeServices
services = RuntimeServices(token_budget=TokenBudget(max_tokens=50_000), budget_guard=BudgetGuard(max_cost_usd=5.0))
```
