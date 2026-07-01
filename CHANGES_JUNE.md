# CEMAF Changes - June 2026

This file is a June-wide summary of the framework changes added in CEMAF during
the current month, including the local replay-helper work on this branch. The
theme across all of it is consistent: move reusable seams into CEMAF so
downstream apps stop rebuilding orchestration, provider wiring, runtime
assembly, observability, and recovery logic on their own.

## Scope

This summary covers:

- major framework additions landed during June 2026
- notable framework-facing fixes that changed runtime behavior or closed gaps
- local June work on this branch that extends the replay surface

It does not try to inventory every docs-only polish commit or every merge
commit. The focus here is framework capability.

## Executive Summary

June materially expanded CEMAF in six directions:

1. CEMAF became more domain-agnostic and more composable as a reusable core.
2. Agent orchestration gained auctions, councils, interceptors, and recovery
   seams.
3. Provider coverage widened across LLM, embeddings, and cloud/local model
   selection.
4. State, memory, retrieval, and improvement loops gained cleaner factory
   surfaces.
5. Observability and replay moved further toward one-call composition.
6. Docs, examples, and CI drift checks got much tighter, which matters because
   this framework now has many more seams to keep aligned.

## Major Framework Additions

### 1. Core platform and framework shape

- `20300b7` `feat(core)!: domain-agnostic core + v2.0.0`
  - Repositioned CEMAF as a reusable framework core rather than a domain-tied
    package.
  - Tightened the public facade around reusable primitives and framework seams.

- `c0107d6` `feat(sandbox): add polyglot ShellSandbox`
  - Added a more general-purpose sandbox surface for code execution workflows.

- `eeb69c1` `feat(skills): polyglot coding skill kit`
  - Added framework-native coding skill packaging for structured tool/coding
    workflows.

- `8f687ec` `feat(framework): cost-aware LLM, sandbox snapshots, durable checkpointing, memory bridge + Makefile fallback`
  - Added cost-aware LLM behavior.
  - Added sandbox snapshot support.
  - Added more durable checkpoint handling.
  - Added a memory bridge seam so memory can participate more naturally in
    larger runtime loops.

- `dd9702d` and `bf8fc5e`
  - Added the hub-and-spoke knowledge graph direction and failure-feedback loop
    framing as first-class framework capabilities.

- `8cbae4d` `fix(security): close two P0 RCE/exfil surfaces from framework audit`
  - Closed two high-severity framework security issues in execution and data
    handling paths.

### 2. Orchestration, agents, and recovery

- `9f4e6ee` `feat(agents): auction-based agent selection`
  - Added auction-style agent routing as a framework primitive.

- `55ded2c` `feat(council): Agent Council`
  - Added deliberative multi-agent council behavior.

- `11cda97` `feat(blueprint): surface the harvest flywheel as a base-layer capability`
  - Promoted the harvest flywheel into a reusable base-layer capability instead
    of leaving it as app-specific logic.

- `96d0d6a` `feat(interceptors): interceptor spine`
  - Introduced the interceptor spine so orchestration concerns can be attached
    at the seam rather than patched into executor/app code.

- `80399af` `feat(interceptors): RECOVER + multi-round council`
  - Added recovery and multi-round deliberation as framework-level control
    paths.

- `9407b6a` `refactor(orchestration): migrate auction + council branches to NodeResolver seam`
  - Consolidated dispatch through the `NodeResolver` seam.

- `184363d` `feat(events): surface recovery + gate-rejected on TASK_COMPLETED payload`
  - Exposed richer event payloads for recovery and gating outcomes.

- `93a7ed7` and `9240c0b`
  - Closed orchestration gaps around council rounds and recovery-attempt
    propagation so the runtime wiring matches the intended control surface.

- `dad25c4` `fix(orchestration): bound FileCheckpointer retention`
  - Added bounded retention to file checkpoints to keep persistence behavior
    sane over long-running usage.

### 3. Model, provider, and generation surface

- `5372c7e` `feat(catalog+llm+retrieval): Hugging Face integration`
  - Added Hugging Face model/provider integration.
  - Extended the model catalog and embeddings path.

- `9a9cda6` `feat(llm): add ollama-cloud provider for free-tier cloud models`
  - Added an Ollama Cloud provider path.

- `e6efff6` `feat(llm): add CEMAF Bedrock CLI provider`
  - Added `BedrockCliLLMClient` and Bedrock-backed factory wiring.

- `ea694e2` `feat(llm): add resilient runtime factory`
  - Added `create_resilient_llm_client(...)` so provider selection, fallback,
    defaults, and resilience wrappers live in CEMAF.

- `16371e1` `feat(generation): add provider resolution helper`
  - Added reusable provider resolution logic so applications do not keep
    reinventing fallback ordering, warning capture, and preflight checks.

### 4. State, memory, retrieval, and improvement runtime

- `a4483ca` `feat(state): cemaf.state`
  - Added a typed, persisted, observable FSM primitive as a proper framework
    subsystem.

- `f1fc0b5` `feat(state): add FSM store factory`
  - Added `create_fsm_store(...)` so consumers can request the standard store
    through a stable factory seam.

- `5c7214f` `feat(memory): add runtime composition factory`
  - Added `MemoryRuntime` and `create_memory_runtime(...)` to compose the
    embedding provider, memory store, vector store, extraction pipeline, memory
    manager, and session management behind one CEMAF surface.

- `3adcc3f` `feat(improvement): add runtime composition helpers`
  - Added improvement runtime composition helpers.

- `bf8eaa3` `feat(improvement): add self-improvement loop factory`
  - Added `create_self_improvement_loop(...)` so apps stop directly
    instantiating the default loop.

- `dd106a2` `feat(retrieval): add sqlite vector store and trace coverage`
  - Added SQLite vector-store support to retrieval composition.
  - Added deeper retrieval/runtime trace coverage around realistic flows.

- `5671264` `fix(sqlite): close test stores deterministically`
  - Tightened SQLite lifecycle behavior around test and temporary store cleanup.

### 5. Runtime composition, moderation, evals, observability, and replay

- `36e00f4` `feat(factories): add runtime services composition helper`
  - Added `create_runtime_services(...)` so apps can delegate standard runtime
    assembly to CEMAF.

- `6a2759f` `feat(factories): add logger and moderation composition helpers`
  - Added factory-owned logger and moderation composition seams.

- `2331fd8` `feat(factories): add CEMAF runtime composition helpers`
  - Broadened factory coverage so common runtime assembly stops living in app
    bootstrap code.

- `237da0e` `feat(factories): support CEMAF-native learning and moderation wiring`
  - Moved more learning/moderation wiring into framework-owned composition.

- `3243389` `feat(evals): add CEMAF composition helpers for eval and recovery`
  - Added factory seams for online eval composition, quality policing, and
    recovery-manager setup.

- `0f1f564` `feat(factories): add moderation and eval composition helpers`
  - Added explicit moderation/eval helpers so blocked-word checks, post-flight
    gating, and eval binding stop being assembled ad hoc by downstream apps.

- `71d5a05` `feat(observability): add file run logger factory backend`
  - Added file-backed run logging so persisted bundles can be selected through
    framework configuration rather than custom app wiring.

- `1519458` `feat(observability): add standard run bundle export helper`
  - Added `export_standard_run_artifacts(...)` to package execution artifacts,
    evidence, model usage, and optional replay/run-record outputs through one
    helper.

- `d235733` `feat(observability): add bundle inspection helpers`
  - Added `inspect_bundle(...)` and `inspect_bundle_record_path(...)` for a
    clean persisted-bundle inspection surface.

- Local branch work:
  - Added `ReplayExecutionBundle` and
    `replay_record_to_artifact(...)` in `cemaf.replay.factories`.
  - This collapses a generic three-step app workflow into one CEMAF helper:
    inspect persisted run bundle -> load `run_record.json` -> replay ->
    export replay artifact.
  - This is exactly the kind of seam that should live in CEMAF rather than in
    each downstream CLI.

## Why These Additions Matter

The practical objective behind nearly all June work was the same:

- stop downstream apps from directly instantiating default framework internals
- stop duplicating provider-selection and fallback logic
- stop rebuilding runtime service assembly locally
- stop scattering moderation, eval, observability, and replay wiring across
  application entrypoints
- make orchestration behaviors configurable at stable seams instead of through
  app-owned glue code

MeridianSight was the immediate forcing function for a lot of this, but the
result is broader than that one app. The new seams are generic CEMAF surfaces.

## Net Effect on the Framework

By the end of June, CEMAF is stronger in the following ways:

- more reusable as a domain-agnostic orchestration core
- broader in provider and backend coverage
- cleaner in runtime assembly through factory surfaces
- more capable in agent routing, councils, recovery, and interception
- more complete in persisted observability and replay handling
- easier to consume from downstream apps without re-implementing framework
  logic

## Local Note

If you want this file to track only merged work, remove the local replay-helper
bullet above once that change is either merged separately or intentionally
dropped. Right now it is included because it is part of the current CEMAF work
on this machine.
