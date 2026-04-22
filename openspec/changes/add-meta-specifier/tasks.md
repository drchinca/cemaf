# Tasks

## 1. Interface types

- [ ] 1.1 Add `SpecGoal` (Pydantic BaseModel, frozen): `feature_description: str`, `change_id: str`, `capabilities: tuple[str, ...]`, `constraints: JSON = {}`
- [ ] 1.2 Add `SpecResult` (Pydantic BaseModel, frozen): `change_id: str`, `proposal: ProposalDoc`, `validation_passed: bool`, `diagnostics: tuple[OpenSpecDiagnostic, ...]`
- [ ] 1.3 Add `ProposalDoc` with nested `CapabilityDelta`, `Requirement`, `Scenario` (all frozen Pydantic)

## 2. Renderer

- [ ] 2.1 Implement `render_proposal(doc: ProposalDoc) -> Mapping[str, str]` — pure function, deterministic output
- [ ] 2.2 Round-trip property: rendering the same ProposalDoc twice produces identical markdown

## 3. Agent

- [ ] 3.1 Implement `MetaSpecifier(Agent[SpecGoal, SpecResult])` — uses LLM to fill `ProposalDoc` from `feature_description`
- [ ] 3.2 When `llm_client` is None, fall back to a deterministic template stub (for tests without an API key)
- [ ] 3.3 Bounded repair loop: if validate fails, feed diagnostics back once; cap retries

## 4. DAG + bootstrap

- [ ] 4.1 Add `create_self_spec_dag()` returning the 3-node DAG
- [ ] 4.2 Extend `RuntimeServices` with `openspec_runtime` + `openspec_workspace` optional fields
- [ ] 4.3 Extend `create_meta_executor()` to register OpenSpec tools + MetaSpecifier when both are present

## 5. Tests

- [ ] 5.1 Contract tests: SpecGoal/Result shape, Agent protocol conformance
- [ ] 5.2 Unit test: `render_proposal` produces valid OpenSpec markdown (header levels, scenario structure)
- [ ] 5.3 Unit test: `MetaSpecifier` with fake `LLMClient` returning canned `ProposalDoc`
- [ ] 5.4 Integration test: self_spec DAG end-to-end with `FakeOpenSpecRuntime` + real `OpenSpecWorkspace`
- [ ] 5.5 Integration test (skipped if `openspec` not on PATH): run against real CLI

## 6. Documentation

- [ ] 6.1 Update CLAUDE.md meta-agent table to include MetaSpecifier + self_spec DAG
