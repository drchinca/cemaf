# ECC-Informed CEMAF Enhancement Research

Research date: 2026-06-25

Primary source: local `ECC/` git repo at `71d22d0a feat(layer4): live messages-table wiring for proximity triggers`

Related local sources reviewed:

- `cemaf/`
- `cemaf-service/`
- `cemaf-mcp/`
- `cemaf_benchmarks/`
- `iccha_autonomy/`
- `meridian_research/`

This note intentionally avoids external claims. The recommendations below are derived from local code, local docs, and repo-to-repo fit.

## Executive Conclusion

ECC and CEMAF are converging on the same system boundary from opposite directions.

ECC is becoming an agent harness operating system. Its strongest pieces are operator-facing: canonical session adapters, control-pane snapshots, selective capability installs, hook runtime policy, MCP inventory normalization, agent proximity advisories, governance capture, and skill evolution records.

CEMAF is already a stronger context and orchestration substrate. Its strongest pieces are protocol-first `RuntimeServices`, immutable `Context` and `ContextPatch`, DAG execution, event emission, run logging, budget and health monitors, eval and moderation gates, memory lifecycle, replay, and self-improvement primitives.

The right enhancement strategy is not to copy ECC into CEMAF. CEMAF should absorb ECC's operational contracts as optional, protocol-shaped services that sit on top of the existing CEMAF runtime.

The highest-leverage move is to add a CEMAF operator plane:

1. A canonical `cemaf.session.v1` snapshot contract.
2. A status reporter over `RunRecord`, `EventBus`, `BudgetGuard`, `HealthMonitor`, `GlassBoxReport`, and `RuntimeServices`.
3. A manifest-backed capability resolver that wires explicit `RuntimeServices` without globals.
4. Runtime policy profiles and tool middleware for hook-like cross-cutting behavior.
5. A verifier-backed self-improvement pipeline with durable proposal and promotion artifacts.
6. An optional collision-risk service for parallel DAG nodes and external workers.
7. MCP/provider inventory normalization with redaction, dedupe, and strict default policy.
8. Context pressure controls that fold in CEMAF's existing tool-output bucket and anchored compaction POCs.

The first implementation should be read-only and low-risk: snapshot models, adapters, and tests. Once a stable status contract exists, service endpoints, MCP resources, capability packs, and risk advisories can all use it.

## Research Corpus

### ECC Evidence

Architecture and contract docs:

- `ECC/docs/ECC-2.0-REFERENCE-ARCHITECTURE.md`
- `ECC/docs/SESSION-ADAPTER-CONTRACT.md`
- `ECC/docs/SELECTIVE-INSTALL-ARCHITECTURE.md`
- `ECC/docs/design/agent-proximity.md`
- `ECC/docs/MCP-CONNECTOR-POLICY.md`
- `ECC/docs/continuous-learning-v2-spec.md`
- `ECC/docs/ARCHITECTURE-IMPROVEMENTS.md`
- `ECC/docs/capability-surface-selection.md`
- `ECC/docs/SKILL-PLACEMENT-POLICY.md`
- `ECC/research/ecc2-codebase-analysis.md`

Runtime code and schemas:

- `ECC/scripts/lib/session-adapters/canonical-session.js`
- `ECC/scripts/lib/control-pane/state.js`
- `ECC/scripts/lib/control-pane/proximity.js`
- `ECC/scripts/lib/agent-proximity/index.js`
- `ECC/scripts/lib/agent-proximity/distance.js`
- `ECC/scripts/lib/mcp-inventory/canonical-mcp.js`
- `ECC/scripts/lib/harness-adapter-compliance.js`
- `ECC/scripts/lib/skill-evolution/versioning.js`
- `ECC/scripts/lib/state-store/schema.js`
- `ECC/schemas/state-store.schema.json`
- `ECC/manifests/install-modules.json`
- `ECC/manifests/install-profiles.json`
- `ECC/hooks/hooks.json`
- `ECC/scripts/hooks/*`

Observed ECC scale signals:

- 271 skill definitions under `ECC/skills`.
- 92 command markdown files.
- 67 agent markdown files.
- Recent git history is actively moving toward live proximity triggers and messages-table integration.

### CEMAF Evidence

Core architecture:

- `cemaf/README.md`
- `cemaf/docs/architecture.md`
- `cemaf/docs/context_engineering_agents.md`
- `cemaf/docs/analysis/SYSTEM_ARCHITECTURE_AND_READINESS.md`
- `cemaf/src/cemaf/orchestration/services.py`
- `cemaf/src/cemaf/orchestration/executor.py`
- `cemaf/src/cemaf/orchestration/node_handlers.py`
- `cemaf/src/cemaf/context/context.py`
- `cemaf/src/cemaf/context/patch.py`
- `cemaf/src/cemaf/context/merge.py`
- `cemaf/src/cemaf/events/protocols.py`
- `cemaf/src/cemaf/events/bus.py`

Observability and runtime:

- `cemaf/src/cemaf/observability/run_logger.py`
- `cemaf/src/cemaf/observability/glass_box.py`
- `cemaf/src/cemaf/observability/budget_guard.py`
- `cemaf/src/cemaf/observability/health.py`
- `cemaf/src/cemaf/observability/cost_tracking.py`
- `cemaf/src/cemaf/replay/*`

Capabilities and tools:

- `cemaf/src/cemaf/skills/*`
- `cemaf/src/cemaf/tools/registry.py`
- `cemaf/src/cemaf/tools/base.py`
- `cemaf/src/cemaf/catalog/*`
- `cemaf/src/cemaf/core/provider_registry.py`
- `cemaf/src/cemaf/mcp/adapter.py`
- `cemaf/src/cemaf/mcp/types.py`

Improvement, trust, memory:

- `cemaf/src/cemaf/improvement/loop.py`
- `cemaf/src/cemaf/improvement/protocols.py`
- `cemaf/src/cemaf/trust/ledger.py`
- `cemaf/src/cemaf/memory/strategy.py`
- `cemaf/src/cemaf/memory/session.py`
- `cemaf/src/cemaf/blueprint/harvest.py`

Validated local POCs that already align with ECC:

- `cemaf/docs/pocs/model-catalog.md`
- `cemaf/docs/pocs/tool-execution-wrapper.md`
- `cemaf/docs/pocs/tool-output-context-bucket.md`
- `cemaf/docs/pocs/anchored-compaction-template.md`

Service and downstream consumers:

- `cemaf-service/README.md`
- `cemaf-service/api/routers/runs.py`
- `cemaf-service/api/routers/capabilities.py`
- `cemaf-service/api/registry.py`
- `cemaf-service/webapp/engine.py`
- `cemaf-mcp/README.md`
- `iccha_autonomy/docs/specs/SPEC-cemaf-embed.md`
- `meridian_research/docs/specs/SPEC-meridian-research-loop-v1.md`
- `cemaf_benchmarks/README.md`

## Transfer Principle

Port ECC's contracts, not ECC's shape.

CEMAF should not become a worktree manager by default. It should not import ECC's skill library wholesale. It should not put a large universal MCP surface into every run. It should not replace `RuntimeServices` with global process state.

CEMAF should use ECC to strengthen the parts that are underdeveloped in CEMAF:

- public runtime snapshots
- operator status
- capability resolution
- hook-like cross-cutting policy
- inventory normalization
- collision advisories
- governance events
- skill and strategy provenance
- verifier-backed promotion

Every new piece should preserve CEMAF's existing rules:

- Protocol-first.
- Explicit dependency injection through `RuntimeServices`.
- No singleton service container.
- Immutable context and patch semantics.
- PULL-context cost model.
- Replayable and auditable state changes.
- Optional services should be absent by default, not hidden globals.

## ECC Patterns Worth Absorbing

### 1. Canonical Session Adapter Contract

ECC's `SESSION-ADAPTER-CONTRACT.md` and `canonical-session.js` establish a stable normalized snapshot shape before any UI, persistence, or harness-specific logic consumes session state.

The important transfer is the adapter rule:

- harness-specific state is normalized first;
- validators enforce required top-level fields;
- unknown optional nested fields are tolerated;
- new top-level fields require a schema version change.

CEMAF has many internal runtime artifacts, but no single public run/session snapshot:

- `RunRecord`
- `ExecutionResult`
- `ContextPatch`
- `BudgetGuard`
- `HealthMonitor`
- `GlassBoxReport`
- `EventBus` history
- `SessionState`
- replay artifacts

Because there is no public operator snapshot, downstream code can drift toward internal coupling. `cemaf-service/api/routers/runs.py` already shows this risk: it exposes an API-local in-memory run shape rather than the core `RunRecord` or DAG executor state.

Recommendation:

- Add a versioned `cemaf.session.v1` contract.
- Generate it from current core runtime objects.
- Validate it before file persistence, API response, or MCP resource output.

### 2. Control Pane Snapshot And State Store

ECC's `control-pane/state.js` builds a single payload from sessions, work items, knowledge graph recall, connector status, unread messages, costs, and optional proximity. It is not just logging; it is operator state.

CEMAF has audit-grade observability through `RunLogger` and `GlassBoxReporter`, but it lacks a live operator-grade status model.

The difference matters:

- Audit reports answer "what happened?"
- Operator snapshots answer "what is happening and what needs attention?"

Recommendation:

- Add `SnapshotReporter` next to `GlassBoxReporter`.
- Keep `RunLogger` as the event/audit source.
- Add an optional state index that summarizes latest run, worker, capability, governance, and risk state.

### 3. Selective Capability Install Manifests

ECC's `SELECTIVE-INSTALL-ARCHITECTURE.md`, `install-modules.json`, and `install-profiles.json` provide a deterministic capability resolution model. ECC can explain:

- what was requested;
- what was resolved;
- what was copied or generated;
- what was transformed;
- what is owned;
- what is repairable;
- what profile was installed;
- what dependency caused a module to appear.

CEMAF has registries and factories, but capability composition is still code-first. There are agents, tools, skills, evals, MCP adapters, memory backends, vector stores, blueprint libraries, selectors, and interceptors, but no manifest-level plan explaining how a runtime stack was assembled.

Recommendation:

- Add `cemaf.capabilities`.
- A manifest resolver should output an explicit wiring plan for `RuntimeServices`, registries, and policy objects.
- It must not mutate globals.

### 4. Harness Adapter Compliance Matrix

ECC's `harness-adapter-compliance.js` uses compliance states:

- `Native`
- `Adapter-backed`
- `Instruction-backed`
- `Reference-only`

CEMAF can reuse this idea for providers and runtime surfaces. Instead of treating every integration as equally supported, CEMAF should label support maturity for:

- LLM providers
- vector stores
- memory backends
- MCP resources
- service APIs
- cloud node executors
- benchmark adapters
- downstream host frameworks

Recommendation:

- Add maturity metadata to capability manifests.
- Expose it in `/v1/capabilities`.
- Use it in status snapshots so operators can see when a run depends on experimental or instruction-only support.

### 5. Agent Proximity And Collision Advisories

ECC's agent-proximity docs and code model multi-agent file-space risk through overlap, dependency coupling, tree proximity, closure rate, and deterministic advisories.

CEMAF should not copy the full file-space model as core orchestration behavior. Its first risk model should be CEMAF-native:

- context keys
- declared node output keys
- artifact IDs
- artifact paths
- shared memory scopes
- shared external resources

Then code-generation integrations can add a git/file adapter later.

Recommendation:

- Add optional `CollisionRiskService` to `RuntimeServices`.
- Invoke it before launching parallel branches and before external worker assignment.
- Emit advisory events.
- Keep `context.merge` as the final deterministic conflict defense.

### 6. MCP Inventory And Default Policy

ECC's MCP policy is unusually practical: default MCP connectors must be universal and must be better as MCP than as CLI/API skills, because every default schema consumes context.

ECC's MCP inventory code also normalizes across harnesses, redacts secrets, deduplicates servers, and reports consistency.

CEMAF already has `mcp/adapter.py`, but it is a bridge, not an inventory or policy layer.

Recommendation:

- Add MCP inventory normalization for CEMAF MCP resources, local service config, and external MCP server config.
- Redact env vars, args, URLs, and token-like values.
- Dedupe connector definitions.
- Adopt a default policy:
  - default MCP resources must be universal and stateful;
  - stateless integrations should be tools or skills;
  - connector schemas should be opt-in through capability packs;
  - status snapshots should show schema/context overhead.

### 7. Hook Runtime Contracts

ECC's hooks are not just scripts. They encode operational guardrails:

- profile-gated runtime intensity: `minimal`, `standard`, `strict`;
- dry-run support;
- pass-through/fail-open behavior for observability hooks;
- bounded stdin;
- path traversal checks;
- governance event capture;
- context and cost monitors;
- quality gates.

CEMAF does not need shell-hook infrastructure in core. It needs the contract behind the hooks:

- profile-controlled cross-cutting behavior;
- bounded tool outputs;
- structured validation failures;
- centralized event emission;
- governance events;
- cost/context pressure warnings.

CEMAF's existing `tool-execution-wrapper` POC already points to the right implementation: middleware at `ToolRegistry.register()`.

Recommendation:

- Implement the tool middleware POC.
- Add runtime policy profiles that configure middleware, budget guard, moderation, evals, and collision risk.
- Surface profile decisions in snapshots.

### 8. Skill Evolution, Provenance, And Placement

ECC distinguishes curated, learned, imported, and evolved skills. It stores versions and evolution logs with observations, inspections, and amendments.

CEMAF's skill layer is deliberately slimmer. That is good. The useful transfer is metadata and promotion control, not ECC's full skill corpus.

Recommendation:

- Add provenance metadata to CEMAF skills, strategies, and blueprint packs.
- Track local-only vs publishable artifacts.
- Require verifier-backed promotion before learned skills become default.
- Add rollback records for promoted strategies and skills.

### 9. Continuous Learning And Self-Improvement

ECC's continuous-learning v2 spec separates observation, scoring, persistence, and evolution into commands/skills.

CEMAF already has `SelfImprovementLoop`, `StrategyMemoryBackend`, and `TrustLedgerBackend`, but the current loop can update strategy/trust directly after scoring. That is acceptable for telemetry but too eager for framework self-mutation.

Recommendation:

- Split improvement into:
  - observation;
  - proposal;
  - verifier result;
  - promotion;
  - rollback.
- Low-risk trust metrics may update immediately.
- Any default behavior change should require a verifier result.

### 10. Governance Capture

ECC's governance capture hooks emit events for secrets, approvals, sensitive paths, and security-relevant tool usage.

CEMAF already has audit, moderation, validation, and security modules, but governance events are not first-class in the event enum.

Recommendation:

- Add governance event types.
- Include governance summary in status snapshots.
- Persist governance events in the optional operator state index.

## CEMAF Current-State Map

### Strong Foundations

CEMAF already has the right architecture for absorbing ECC patterns cleanly.

`RuntimeServices` is the composition root. It carries optional services such as:

- run logger
- event bus
- health monitor
- budget guard
- eval pipeline
- quality police
- memory manager
- session manager
- moderation pipeline
- context compiler
- LLM client
- vector store
- knowledge graph
- agent selector
- council aggregator
- interceptor pipeline
- blueprint library and selector
- auto-heal manager
- tracer

This is the correct place for optional operator-plane services such as:

- snapshot reporter
- capability resolver
- collision risk service
- governance sink
- model selector
- MCP inventory provider
- improvement artifact store

The DAG executor already accepts `RuntimeServices`, emits events, logs runs, checks health, honors halt signals, runs moderation/evals/quality gates, and handles session bootstrap/dispose.

The context layer already enforces immutable patches and deterministic merge behavior. This is the right final defense for conflicts even after collision advisories are added.

Replay support already provides a path for deterministic verification and regression artifacts.

### Gaps

The main gaps are operational, not conceptual.

1. No canonical public status snapshot.
2. No stable run/session JSON schema for downstream APIs and MCP resources.
3. `cemaf-service` run APIs are API-local scaffolds, not core runtime projections.
4. Capability composition is scattered across factories, registries, and service constructors.
5. Self-improvement has memory/trust primitives but no proposal-verifier-promotion artifact chain.
6. Parallel node conflict detection happens after execution through context merge, not before execution as advisory scheduling input.
7. MCP is a bridge, not an inventory, policy, or schema-cost layer.
8. Tool execution lacks centralized middleware in current source, though a POC exists.
9. Tool outputs are not yet a separate context bucket in source, though a POC exists.
10. Session compaction is item-level, not anchored session-level, though a POC exists.
11. Model/provider metadata exists in catalog pieces and POCs but is not yet the single source of truth for routing, budget, and status.
12. Governance events are not yet a first-class runtime stream.

## Recommended Target Architecture

### Operator Plane

Add an optional operator plane around the existing runtime.

It should have four public contracts:

1. `cemaf.session.v1`
2. `cemaf.capability.v1`
3. `cemaf.runtime_policy.v1`
4. `cemaf.improvement.v1`

It should have five optional services:

1. `SnapshotReporter`
2. `CapabilityResolver`
3. `RuntimePolicy`
4. `CollisionRiskService`
5. `ImprovementArtifactStore`

It should feed four surfaces:

1. CLI: `cemaf status --json`, `cemaf capabilities --dry-run`.
2. Service: `/v1/runs/{id}/status`, `/v1/capabilities/resolve`.
3. MCP: `cemaf://runs/{id}/status`, `cemaf://capabilities`.
4. Replay/benchmarks: stable JSON artifacts.

### Contract Boundary

The operator plane must be read-only by default.

Read-only:

- snapshots;
- inventories;
- status;
- capability dry-runs;
- governance summaries;
- verifier results.

Write-capable only through explicit APIs:

- start run;
- cancel run;
- install capability pack;
- promote improvement proposal;
- rollback promoted artifact.

## Canonical Snapshot Contract

### Initial Shape

```json
{
  "schemaVersion": "cemaf.session.v1",
  "adapterId": "cemaf-dag",
  "run": {
    "id": "run_123",
    "state": "running",
    "dagName": "research_report",
    "startedAt": "2026-06-25T12:00:00Z",
    "endedAt": null
  },
  "workers": [
    {
      "id": "node.research",
      "kind": "dag-node",
      "state": "running",
      "health": "healthy",
      "runtime": {
        "kind": "agent",
        "active": true,
        "dead": false
      },
      "intent": {
        "objective": "Retrieve evidence",
        "inputKeys": ["topic"],
        "outputKeys": ["sources", "notes"]
      },
      "context": {
        "patchCount": 3,
        "inputTokens": 8400,
        "outputTokensReserved": 2000,
        "pressure": "normal"
      },
      "risk": {
        "budget": "normal",
        "quality": "unknown",
        "moderation": "clear",
        "citation": "unknown",
        "collision": "clear"
      },
      "artifacts": {
        "runRecord": "runs/run_123.json"
      }
    }
  ],
  "runtime": {
    "profile": "standard",
    "services": {
      "runLogger": "enabled",
      "eventBus": "enabled",
      "budgetGuard": "enabled",
      "healthMonitor": "enabled",
      "collisionRiskService": "absent"
    }
  },
  "context": {
    "patchCount": 12,
    "tokenBudget": 64000,
    "inputTokens": 18400,
    "pressure": "normal",
    "toolOutput": {
      "kept": 5,
      "evicted": 0,
      "reserveFraction": 0.25
    }
  },
  "risk": {
    "budget": "normal",
    "quality": "unknown",
    "moderation": "clear",
    "collision": "clear",
    "governance": "clear"
  },
  "aggregates": {
    "workerCount": 1,
    "states": {"running": 1},
    "healths": {"healthy": 1},
    "unreadMessages": 0,
    "toolCalls": 2,
    "llmCalls": 1,
    "totalCostUsd": 0.12
  }
}
```

### Adapter Sources

The first snapshot adapters should be:

- `RunRecord` to snapshot.
- `ExecutionResult` to snapshot.
- live executor event accumulator to snapshot.
- external worker/session to snapshot later.

Do not block the first PR on live streaming. Start with deterministic conversion from recorded objects.

### Snapshot States

Use a small state enum:

- `pending`
- `running`
- `blocked`
- `paused`
- `completed`
- `failed`
- `cancelled`
- `stopped`
- `unknown`

Use a small health enum:

- `healthy`
- `degraded`
- `stale`
- `failed`
- `unknown`

This mirrors ECC's operator discipline while staying runtime-agnostic.

## Capability Pack Design

### Manifest Shape

```json
{
  "schemaVersion": "cemaf.capability.v1",
  "id": "research.standard",
  "description": "Research runtime with retrieval, citations, grounding evals, and status snapshots.",
  "kind": "profile",
  "targets": ["cemaf-core", "cemaf-service", "cemaf-mcp"],
  "stability": "stable",
  "cost": "medium",
  "defaultInstall": false,
  "modules": [
    {
      "id": "runtime.snapshot",
      "kind": "runtime_service",
      "provides": ["SnapshotReporter"],
      "dependencies": ["observability.run_logger", "events.bus"]
    },
    {
      "id": "evals.grounding",
      "kind": "eval_binding",
      "provides": ["GroundingEvaluator"],
      "dependencies": ["citation.tracker"]
    },
    {
      "id": "mcp.status",
      "kind": "mcp_resource",
      "provides": ["cemaf://runs/{run_id}/status"],
      "dependencies": ["runtime.snapshot"]
    }
  ],
  "policies": {
    "runtimeProfile": "standard",
    "mcpDefault": false,
    "requiresVerifierForPromotion": true
  }
}
```

### Module Kinds

Recommended CEMAF-specific kinds:

- `runtime_service`
- `agent`
- `skill`
- `tool`
- `tool_middleware`
- `eval_binding`
- `moderation_rule`
- `memory_backend`
- `retriever`
- `vector_store`
- `model_catalog`
- `model_selector_policy`
- `mcp_connector`
- `mcp_resource`
- `blueprint_pack`
- `interceptor`
- `scheduler_gate`
- `benchmark_suite`

### Resolver Output

The resolver should not install silently. It should return:

- requested pack IDs;
- resolved module IDs;
- dependency graph;
- target compatibility;
- service wiring plan;
- registry registrations;
- MCP resources/connectors;
- policy changes;
- missing prerequisites;
- ownership;
- repairability;
- estimated schema/token overhead;
- stability warnings.

This gives CEMAF the same deterministic "why is this capability here?" story that ECC gets from selective install.

## Runtime Policy Profiles

ECC uses hook profiles. CEMAF should use runtime profiles.

Initial profiles:

- `minimal`
- `standard`
- `strict`
- `research`
- `regulated`
- `codegen`

Each profile should configure optional behaviors, not change core invariants.

Example:

```json
{
  "schemaVersion": "cemaf.runtime_policy.v1",
  "id": "strict",
  "toolMiddleware": [
    "span",
    "exception_capture",
    "validation",
    "truncate",
    "permission_guard"
  ],
  "budget": {
    "haltOnExceeded": true,
    "warnAtFraction": 0.8
  },
  "context": {
    "toolOutputReserveFraction": 0.25,
    "anchoredCompaction": true
  },
  "evals": {
    "qualityPolice": "gate",
    "grounding": "gate",
    "citationCoverage": "observe"
  },
  "collision": {
    "enabled": true,
    "resolutionAdvisoryPolicy": "pause_lower_priority"
  },
  "governance": {
    "captureSensitiveToolUsage": true,
    "requireApprovalForPromotion": true
  }
}
```

Runtime profiles should be passed through `RuntimeServices` or executor config. They should not be global process flags.

## Tool Middleware And Context Pressure

CEMAF already has local POCs that should be promoted into the roadmap:

- `tool-execution-wrapper.md`
- `tool-output-context-bucket.md`
- `anchored-compaction-template.md`

ECC's hook lessons make these POCs more important.

Recommended order:

1. Tool middleware chain at `ToolRegistry.register()`.
2. Per-call output truncation with structured metadata.
3. `ContextType.TOOL_OUTPUT`.
4. Adaptive LRU tool-output bucket before general context selection.
5. Anchored session compaction with stable Markdown sections and verbatim recent tail.
6. Snapshot integration for context pressure and evictions.

This gives CEMAF a cleaner core-native alternative to shell hooks:

- middleware handles per-tool execution concerns;
- context bucket handles cross-turn tool-output pressure;
- compactor preserves long-horizon goals and constraints;
- snapshot reporter shows pressure and churn.

## Model And Provider Catalog

CEMAF has `catalog/*`, provider registries, hardcoded budget defaults, and a validated POC for data-driven model selection.

ECC's manifest and inventory work strengthens the case for making provider/model metadata a first-class source of truth.

Recommendation:

- Implement the local model-catalog POC as the model/provider metadata layer.
- Use it for:
  - model selection;
  - context window enforcement;
  - capability gating;
  - cost calculation;
  - status snapshots;
  - capability resolver warnings.
- Keep existing provider factories as construction code.
- Move routing policy into catalog-backed selector.

Important local fit:

- `cemaf/src/cemaf/context/budget.py` currently has model-specific limits inline.
- This should become catalog data to avoid stale runtime assumptions.

## MCP And Provider Inventory

Add a normalized inventory format:

```json
{
  "schemaVersion": "cemaf.inventory.v1",
  "generatedAt": "2026-06-25T12:00:00Z",
  "mcp": {
    "serverCount": 2,
    "duplicateServerCount": 0,
    "inconsistentServerCount": 0,
    "serversWithSecrets": 0
  },
  "providers": {
    "llm": ["anthropic", "openai", "ollama"],
    "vector": ["sqlite", "pgvector"],
    "memory": ["sqlite", "postgres", "redis"]
  },
  "redaction": {
    "envValuesRedacted": 4,
    "urlSecretsRedacted": 1
  }
}
```

This should be read-only. Its purpose is to help operators understand runtime wiring and schema/context overhead.

## Verified Self-Improvement

### Current CEMAF State

CEMAF has useful pieces:

- `SelfImprovementLoop`
- `ExecutionSummary`
- `ImprovementOutcome`
- `StrategyMemoryBackend`
- `TrustLedgerBackend`
- blueprint harvesting
- replay artifacts

But there is no durable proposal-verifier-promotion chain.

### Recommended Contract

```python
@dataclass(frozen=True)
class ImprovementProposal:
    id: str
    source_run_id: str
    kind: str
    target: str
    hypothesis: str
    change_summary: str
    evidence_refs: tuple[str, ...]
    rollback_plan: str

@dataclass(frozen=True)
class VerificationResult:
    proposal_id: str
    passed: bool
    score: float
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    artifacts: tuple[str, ...]

class ImprovementVerifier(Protocol):
    async def verify(self, proposal: ImprovementProposal) -> VerificationResult:
        ...
```

Promotion rule:

- trust metrics can update immediately;
- learned recommendations can be stored immediately;
- default strategy, skill, blueprint, or runtime policy changes require a passing verifier;
- every promotion must have a rollback record.

This turns CEMAF self-improvement from "record better outcomes" into "ship verified improvements."

## Collision Risk Service

### Why CEMAF Needs It

CEMAF already has deterministic merge conflict handling in `context/merge.py`. That is necessary but late.

Parallel agents can waste work or create avoidable conflicts before merge:

- two nodes writing the same context key;
- two codegen nodes editing the same artifact;
- a retrieval node and summarizer fighting over a shared output;
- external workers touching the same worktree paths;
- human review and agent mutation racing on the same artifact.

### First Version

Start with CEMAF-native working sets:

```python
@dataclass(frozen=True)
class WorkingSet:
    owner_id: str
    context_keys: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    memory_scopes: tuple[str, ...] = ()
    weight: float = 1.0

@dataclass(frozen=True)
class CollisionAdvisory:
    level: str  # clear, traffic_advisory, resolution_advisory
    risk: float
    owners: tuple[str, ...]
    reasons: tuple[str, ...]
    recommended_action: str | None = None

class CollisionRiskService(Protocol):
    async def assess(self, working_sets: tuple[WorkingSet, ...]) -> tuple[CollisionAdvisory, ...]:
        ...
```

Policy actions:

- emit only;
- pause lower-priority branch;
- serialize branches;
- request handoff summary;
- retarget artifact;
- require human approval.

Do not mutate scheduling in v1. Emit advisories first, then add policy enforcement once status and tests prove the signal is useful.

## Operator State Store

ECC has a JSON schema and state-store shape for sessions, skill runs, decisions, install state, governance events, and work items.

CEMAF should not replace its run logger or memory stores. It should add an optional operator index.

Suggested tables/entities:

- `run_snapshots`
- `worker_snapshots`
- `capability_packs`
- `capability_install_state`
- `runtime_profiles`
- `improvement_proposals`
- `verification_results`
- `promotion_records`
- `skill_versions`
- `governance_events`
- `inventory_snapshots`

The operator index should be rebuildable from durable artifacts where possible.

## Service Integration

`cemaf-service/webapp/engine.py` already composes a real CEMAF stack. That is the right integration point.

`cemaf-service/api/routers/runs.py` currently uses API-local in-memory run records. That should become a projection over core snapshots.

Recommended service endpoints:

- `GET /v1/runs/{run_id}/status`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/glass-box`
- `POST /v1/capabilities/resolve`
- `GET /v1/capabilities`
- `GET /v1/inventory`
- `GET /v1/improvements/{proposal_id}`
- `POST /v1/improvements/{proposal_id}/promote`

Keep write endpoints explicit and permissioned.

## MCP Integration

`cemaf-mcp` should expose narrow, high-value resources first:

- `cemaf://runs/{run_id}/status`
- `cemaf://runs/{run_id}/glass-box`
- `cemaf://capabilities`
- `cemaf://inventory`

Avoid default broad tool schemas. The default MCP connector should report and inspect CEMAF state, not expose every tool in the framework.

## Downstream Fit

### `iccha_autonomy`

The local CEMAF embed spec says downstream code wants CEMAF to provide ingestion, lifecycle, context, evals, budget, retry, observability, composition root, plan compiler, node executor, artifact store, and stable IDs.

The snapshot/capability/artifact recommendations directly support this:

- stable run IDs;
- stable artifact references;
- service wiring plan;
- operator status;
- cloud/local node visibility;
- eval and budget status;
- replayable artifacts.

### `meridian_research`

The local research-loop spec needs run IDs, cost, events, citations, grounding, and retrievers.

Snapshot and model catalog work support:

- per-run cost;
- citation coverage;
- grounding gates;
- retrieval capability packs;
- MCP/status visibility;
- replayable research artifacts.

### `cemaf_benchmarks`

The benchmark repo should consume stable result artifacts rather than framework internals.

Recommended benchmark artifacts:

- `cemaf.session.v1`
- `GlassBoxReport`
- replay export
- eval result bundle
- model/catalog selection trace
- capability manifest used for the run

## Prioritized Roadmap

### P0: `cemaf.session.v1` Snapshot Models

Deliver:

- `cemaf/src/cemaf/observability/snapshot.py`
- frozen dataclasses or Pydantic models;
- JSON schema export;
- `RunRecord` adapter;
- `ExecutionResult` adapter;
- aggregate calculation;
- unit tests with golden JSON fixtures;
- docs page `cemaf/docs/session_snapshot.md`.

Acceptance:

- converting the same `RunRecord` twice produces identical JSON except timestamps supplied by input;
- unknown nested metadata survives;
- invalid top-level schema version is rejected;
- aggregate states and health counts are deterministic;
- no DAG execution behavior changes.

### P1: Snapshot Reporter And Status Surfaces

Deliver:

- `SnapshotReporter`;
- `cemaf status --json` or internal CLI equivalent;
- service endpoint projection;
- MCP resource projection;
- snapshot section in `GlassBoxReport` or link from report to snapshot.

Acceptance:

- a completed run can be inspected through core, service, and MCP surfaces with the same schema;
- missing optional services appear as `absent`, not errors;
- budget and health state appear when services are present;
- no service endpoint returns API-local run state when core snapshot state exists.

### P2: Capability Manifest Resolver

Deliver:

- `cemaf/src/cemaf/capabilities/models.py`
- `cemaf/src/cemaf/capabilities/resolver.py`
- `cemaf/src/cemaf/capabilities/manifests.py`
- example packs: `minimal`, `research`, `codegen`, `regulated`;
- dry-run resolver;
- service `/v1/capabilities/resolve`.

Acceptance:

- resolver explains requested, resolved, skipped, missing, and incompatible modules;
- resolver emits a wiring plan, not side effects;
- profiles produce deterministic module order;
- target compatibility is checked;
- schema/context overhead is estimated for MCP/tool modules.

### P3: Runtime Policy Profiles And Tool Middleware

Deliver:

- runtime policy model;
- default profiles;
- tool middleware chain from the POC;
- span, validation, exception-capture, truncation middlewares;
- profile-driven middleware selection.

Acceptance:

- all registered tools execute through default middleware unless explicitly bypassed;
- oversized outputs are truncated with metadata;
- validation errors are structured;
- exceptions become failed tool results with metadata;
- middleware decisions appear in snapshots.

### P4: Context Pressure Controls

Deliver:

- `ContextType.TOOL_OUTPUT`;
- adaptive tool-output bucket;
- eviction events;
- anchored session compactor;
- snapshot pressure fields.

Acceptance:

- recent tool outputs are protected up to reserve;
- stale tool outputs evict deterministically;
- anchored compaction preserves prior goals, constraints, decisions, current task, and relevant files;
- context pressure is visible in status snapshots.

### P5: Model Catalog And Provider Inventory

Deliver:

- model catalog schema/data;
- catalog-backed selector;
- provider inventory snapshot;
- redaction helpers;
- cost calculation from catalog;
- migration of hardcoded context limits into catalog data.

Acceptance:

- model selection gates on capability and context window;
- cheapest qualified model wins within quality floor;
- deprecated models are skipped unless explicitly requested;
- costs can be derived for status reports;
- inventory redacts secrets.

### P6: Verified Self-Improvement

Deliver:

- proposal models;
- verifier protocol;
- artifact store;
- promotion record;
- rollback record;
- integration with `SelfImprovementLoop`.

Acceptance:

- failed verifier blocks promotion;
- passing verifier is required for default behavior changes;
- rollback can restore previous promoted artifact;
- trust metric updates can still happen without promotion.

### P7: Collision Risk Service

Deliver:

- `CollisionRiskService` protocol;
- working-set model;
- context key/artifact overlap detector;
- event types;
- snapshot integration;
- advisory-only mode;
- later policy enforcement.

Acceptance:

- parallel nodes with overlapping declared outputs generate advisory;
- non-overlapping nodes remain clear;
- advisories do not mutate scheduler in v1;
- merge conflict behavior remains unchanged.

### P8: MCP Inventory And Policy

Deliver:

- normalized MCP inventory;
- redaction and dedupe;
- default connector policy doc;
- capability-pack-gated MCP resources.

Acceptance:

- default MCP surface is narrow;
- stateless integrations are not default MCP connectors;
- duplicate/inconsistent server config is reported;
- schema overhead appears in capability dry-run and status.

### P9: Skill And Strategy Provenance

Deliver:

- provenance model for skills, strategies, and blueprint packs;
- version records;
- local-only vs publishable flag;
- promotion linkage to verifier results.

Acceptance:

- learned artifacts are local-only by default;
- promoted artifacts cite verifier result;
- rollback restores prior version;
- provenance appears in capability/status output.

## First Three PRs

### PR 1: Snapshot Contract

Scope:

- `cemaf/src/cemaf/observability/snapshot.py`
- `cemaf/tests/observability/test_snapshot.py`
- `cemaf/docs/session_snapshot.md`

No service changes. No executor behavior changes.

Why first:

- creates the public contract;
- low blast radius;
- gives all later work a stable target.

### PR 2: Snapshot Reporter And Service Projection

Scope:

- `SnapshotReporter`;
- adapter from `RunRecord` and optional services;
- `cemaf-service` status endpoint;
- MCP resource if dependency wiring is already present.

Why second:

- proves the schema works outside core;
- replaces API-local run scaffolding gradually.

### PR 3: Capability Resolver Dry Run

Scope:

- manifest models;
- resolver;
- sample packs;
- dry-run API/CLI;
- no automatic install.

Why third:

- creates repeatable runtime composition;
- sets up model catalog, MCP inventory, and profile work.

## Non-Goals

Do not do these in the first wave:

- Do not copy ECC's worktree/session manager into CEMAF core.
- Do not import ECC's full skill corpus.
- Do not expose every CEMAF tool through default MCP.
- Do not make runtime profiles global process state.
- Do not let capability manifests mutate registries implicitly.
- Do not let self-improvement promote default behavior without verifier artifacts.
- Do not enforce collision pauses before advisory signal quality is tested.
- Do not replace `RunLogger`, memory stores, or replay with an operator store.

## Risks And Mitigations

### Risk: Operator Plane Becomes A Second Runtime

Mitigation:

- make it read-only first;
- generate snapshots from existing runtime artifacts;
- keep executor semantics unchanged until advisories are proven.

### Risk: Capability Packs Become Hidden Global Installers

Mitigation:

- resolver returns wiring plans;
- composition root applies plans explicitly;
- every side effect is an explicit API call.

### Risk: Snapshot Schema Freezes Too Early

Mitigation:

- version it from day one;
- allow unknown optional nested fields;
- block unknown top-level fields unless version changes.

### Risk: MCP Surface Bloats Context

Mitigation:

- default MCP policy from ECC;
- opt-in capability packs;
- schema overhead estimate in dry-run and status.

### Risk: Improvement Pipeline Slows Learning

Mitigation:

- keep immediate telemetry and trust updates;
- require verifier only for promoted behavior changes.

### Risk: Collision Advisories Add Noise

Mitigation:

- start with advisory-only mode;
- record precision/recall in status and benchmarks;
- gate enforcement by runtime profile.

## Design Rules For Implementation

1. New cross-cutting services belong in `RuntimeServices` or explicit config.
2. Public JSON gets a schema and golden fixture.
3. New runtime events must have stable event names and payload docs.
4. Optional service absence must be represented, not treated as failure.
5. Capability resolution must be deterministic.
6. Status surfaces must not expose secrets.
7. Promotion needs verifier artifacts.
8. Tool and MCP schema overhead must be visible.
9. Replay artifacts must remain enough to reproduce decisions.
10. Downstream consumers should depend on public contracts, not internal dataclasses.

## Summary

ECC's core lesson for CEMAF is operationalization. CEMAF already has the context engine, DAG executor, memory system, eval gates, replay, and protocol discipline. What it lacks is the operator contract layer that turns those internals into stable, inspectable, composable runtime surfaces.

The most useful path is:

1. snapshot contract;
2. status reporter;
3. capability resolver;
4. runtime profiles and tool middleware;
5. context pressure controls;
6. model/provider inventory;
7. verified improvement;
8. collision advisories;
9. narrow MCP resources.

That order keeps early changes read-only, preserves CEMAF's architecture, and uses ECC's best ideas where they fit: at the boundary between orchestration internals and real operators.
