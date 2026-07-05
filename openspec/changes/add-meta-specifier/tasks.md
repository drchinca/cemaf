# Tasks

## 1. Interface types

- [x] 1.1 Add `SpecGoal` (Pydantic BaseModel): `feature_description: str`, `change_id: str`, `capabilities: tuple[str, ...]`, `constraints: JSON = {}`
- [x] 1.2 Add `SpecResult` (Pydantic BaseModel, frozen): `change_id: str`, `proposal: ProposalDoc`, `validation_passed: bool`, `diagnostics: tuple[dict[str, str], ...]`
- [x] 1.3 Add `ProposalDoc` with nested `CapabilityDelta`, `Requirement`, `Scenario` (all frozen Pydantic)

## 2. Renderer

- [x] 2.1 Implement `render_proposal(doc: ProposalDoc) -> Mapping[str, str]` — pure function, deterministic output
- [x] 2.2 Round-trip property: rendering the same ProposalDoc twice produces identical markdown

## 3. Agent

- [x] 3.1 Implement `MetaSpecifier(Agent[SpecGoal, SpecResult])` — uses LLM to fill `ProposalDoc` from `feature_description`
- [x] 3.2 When `llm_client` is None, fall back to a deterministic template proposal (for tests without an API key)
- [x] 3.3 Bounded repair loop: if validate fails, feed diagnostics back once; cap retries

## 4. DAG + bootstrap

- [x] 4.1 Add `create_self_spec_dag()` returning the Specifier -> Auditor DAG
- [x] 4.2 Extend `MetaServices` with `openspec_runtime` + `openspec_workspace` optional fields
- [x] 4.3 Extend `create_meta_executor()` to register OpenSpec tools + MetaSpecifier when a workspace is present

## 5. Tests

- [x] 5.1 Contract tests: SpecGoal/Result shape, Agent protocol conformance
- [x] 5.2 Unit test: `render_proposal` produces valid OpenSpec markdown (header levels, scenario structure)
- [x] 5.3 Unit test: `MetaSpecifier` with fake `LLMClient` returning canned `ProposalDoc`
- [x] 5.4 Integration test: self_spec DAG end-to-end with `FakeOpenSpecRuntime` + real `OpenSpecWorkspace`
- [x] 5.5 Integration test (skipped if `openspec` not on PATH): run against real CLI

## 6. Documentation

- [x] 6.1 Update CLAUDE.md meta-agent table to include MetaSpecifier + self_spec DAG
