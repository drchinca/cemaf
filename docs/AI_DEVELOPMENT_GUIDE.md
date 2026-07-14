# CEMAF: AI Integration & Development Guide

> **AI System Rule:** You are extending or leveraging CEMAF. Do NOT reinvent its core components. CEMAF is a protocol-driven, zero-leak Context Engineering Engine. Follow these strict architectural invariants.

---

## 1. Architectural Guardrails (Do vs. Violation)

| Intent | ❌ VIOLATION (Procedural / Redundant) | Decisive CEMAF Way (Native & Optimized) |
| :--- | :--- | :--- |
| **Prompting** | String f-strings or Jinja2 templates in Python files. | **Semantic Blueprints** (`cemaf.blueprint`). Registries of typed, versioned `Blueprint` structures. |
| **Learning** | Manually saving runs or hardcoding self-correction loops. | **Blueprint Harvester Engine** (`cemaf.blueprint.harvest`). Scoped continuous learning (Accrual & Promotion). |
| **Context Trim** | Manual message list-slicing or LLM-based summary on every turn. | **Anchored Compaction** (`cemaf.memory`). Zero-cost, deterministic `SimpleMemoryCompactor` with a 25% tail budget. |
| **Function calls** | Procedural dictionary parsing or custom try-except loops. | **Tool Execution Wrapper** (`cemaf.tools`). Decorator `@tool` + `ToolRegistry` with standardized JSON validation errors. |
| **Content Safety** | Regex filters or security checks inside agent run loops. | **Moderation Pipeline** (`cemaf.moderation`) wired as PRE/POST `cemaf.interceptors`. Safety runs at interceptor boundaries, never inside agent code. |
| **Context Hydration** | Querying databases or vector search inside Agent code. | **Pull Interceptor** (`cemaf.interceptors`). Automatic data hydration at `PRE` phase. |

---

## 2. Strict Python Standards

1. **Behavior**: Use `typing.Protocol` (PEP 544 structural typing). Avoid ABC inheritance unless physical runtime registration is required.
2. **Generics**: Use PEP 695 inline generic syntax: `type Result[T] = T | Exception`.
3. **State**: Standardize on `@dataclass(frozen=True, slots=True)` for domain models.
4. **Boundary**: Never leak database/ORM models outside of repository layers. Map to pure domain models before returning.

---

## 3. High-Density Integration Recipes

### Recipe A: Context & ContextPatch (SPEC-00/SPEC-11 Data Governance)
Do not use mutable shared dicts for agent state. Leverage immutable `Context` and `ContextPatch` with strict SPEC-11 security classifications for full data governance and auditability.

```python
from datetime import datetime
from typing import Any
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchOperation, PatchSource, SecurityLevel
from cemaf.core.utils import utc_now

# 1. Define a secure, immutable context patch (SPEC-11 data governance)
privacy_patch = ContextPatch(
    path="user.profile.ssn",
    operation=PatchOperation.SET,
    value="[REDACTED]",
    source=PatchSource.SYSTEM,
    source_id="pii_anonymizer",
    timestamp=utc_now(),
    reason="Automatic scrubbing of sensitive PII in public boundary",
    security_level=SecurityLevel.CONFIDENTIAL  # SPEC-11 data sensitivity rank gating
)

# 2. Apply patch to immutable Context (returns a new Context instance)
base_context = Context(data={"user": {"profile": {"name": "Alice", "ssn": "123-45-678"}}})
secure_context = base_context.apply(privacy_patch)

# 3. Verify immutability & provenance-aware hashing
assert secure_context.get("user.profile.ssn") == "[REDACTED]"
assert base_context.get("user.profile.ssn") == "123-45-678"  # Base unchanged

# Fetch complete timeline (provenance trail) for audits
provenance_trail = secure_context.get_timeline()
for patch in provenance_trail:
    print(f"[{patch.timestamp}] {patch.source_id} modified '{patch.path}' (Security: {patch.security_level.value})")

# Generate deterministic hash of the complete data + patch history
cache_key = secure_context.state_hash()
```

### Recipe B: Scoped Blueprints & Promotion (SPEC-03/SPEC-13 Harvest)
Do not hardcode f-strings or prompt templates. Leverage the `BlueprintLibrary` to manage prompt lifecycles, and use SPEC-13 scoped promotions to prevent React blueprints from leaking into Django domains.

```python
from cemaf.blueprint import Blueprint, SceneGoal, StyleGuide, BlueprintScope
from cemaf.blueprint.library import BlueprintLibrary, BlueprintEntry, BlueprintEntryKind
from cemaf.blueprint.harvest_defaults import evaluate_promotion, ProjectScopedRecipeDistiller

# 1. Register a project-scoped Recipe Blueprint
library = BlueprintLibrary()
library.register(entry=BlueprintEntry.recipe_entry(
    id="harvest/project-alpha/haiku-writer",
    title="Alpha Haiku Specialist",
    recipe={
        "name": "HaikuWriter",
        "scene_goal": {"objective": "Write a short Zen-like poem", "priority": 1},
        "style_guide": {"tone": "contemplative", "format": "markdown"}
    },
    project_id="project-alpha",
    confidence=0.9,
    scope=BlueprintScope.PROJECT  # Scoped to alpha domain (SPEC-13)
))

# 2. Evaluate Continuous-Learning Promotion (SPEC-13)
# When the same semantic goal is harvested across >=2 distinct projects, promote to GLOBAL
harvested_entries = (
    BlueprintEntry.recipe_entry(
        id="harvest/project-alpha/a1b2c3d4",
        title="Promoted Poem",
        recipe={"name": "Poem"},
        project_id="project-alpha",
        confidence=0.95
    ),
    BlueprintEntry.recipe_entry(
        id="harvest/project-beta/a1b2c3d4",
        title="Promoted Poem",
        recipe={"name": "Poem"},
        project_id="project-beta",
        confidence=0.85
    )
)

decisions = evaluate_promotion(harvested_entries, min_projects=2, min_confidence=0.8)
for decision in decisions:
    if decision.promote:
        # Re-register as GLOBAL so all workspace engines can leverage it
        global_blueprint = library.resolve(f"harvest/project-alpha/{decision.blueprint_key}")
        library.register(
            entry=BlueprintEntry.snapshot_entry(
                id=f"global/{decision.blueprint_key}",
                title="Earned Global Standard",
                blueprint=global_blueprint,
                scope=BlueprintScope.GLOBAL
            ),
            overwrite=True
        )
```

### Recipe C: Bounded Infrastructure Self-Healing (SPEC-06/AutoHealManager)
Do not build custom retry loops or error fallback structures inside agent classes. Implement custom `RecoveryStrategy` classes and register them directly onto the `AutoHealManager` for centralized self-healing.

```python
from typing import Any
from cemaf.core.recovery import RecoveryStrategy, AutoHealManager
from cemaf.context.context import Context
from cemaf.context.patch import ContextPatch, PatchOperation
from cemaf.core.result import Result

# 1. Define custom infrastructure recovery strategy
class VectorStoreFallbackStrategy(RecoveryStrategy):
    """Fallback to sparse text indexing if dense vector searches timeout/fail."""

    def recover(self, error_result: Result[Any], context: Context) -> Result[Context]:
        # Log failure reason (extracted from the result metadata)
        failed_with = error_result.metadata.get("exception_type", "Unknown")
        print(f"[AutoHeal] Handling infrastructure error '{failed_with}'. Redirecting search to sparse...")

        # Inject recovery directive patch into Context
        heal_patch = ContextPatch(
            path="infrastructure.retrieval_mode",
            operation=PatchOperation.SET,
            value="sparse",
            reason=f"AutoHeal: Redirected due to dense vector failure: {error_result.error}"
        )
        return Result.ok(context.apply(heal_patch))

# 2. Register with AutoHealManager
auto_heal = AutoHealManager()
auto_heal.register(error_type="VectorStoreTimeout", strategy=VectorStoreFallbackStrategy())

# 3. Execute recovery when execution fails
failed_run = Result.fail(
    error="Connection to vector store timed out after 5000ms",
    metadata={"exception_type": "VectorStoreTimeout"}
)

current_context = Context(data={"infrastructure": {"retrieval_mode": "dense"}})

# Heal manages fallback chain: exact match -> regex match -> default strategy
heal_result = auto_heal.heal(failed_run, current_context)
if heal_result.success:
    recovered_context = heal_result.unwrap()
    assert recovered_context.get("infrastructure.retrieval_mode") == "sparse"
```
