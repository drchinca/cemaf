# meta-specifier capability

## ADDED Requirements

### Requirement: MetaSpecifier produces a structured ProposalDoc from a feature description

The system SHALL provide a MetaSpecifier agent that consumes a `SpecGoal` and returns a `SpecResult` containing a typed `ProposalDoc`, rendered markdown files, and a validation outcome.

#### Scenario: Happy path — valid proposal passes strict validation

- **GIVEN** a MetaSpecifier wired to an `LLMClient` that returns a well-formed `ProposalDoc` and an `OpenSpecWorkspace` bound to a scratch directory
- **WHEN** the agent runs with `SpecGoal(feature_description="add session replay", change_id="add-session-replay", capabilities=("replay",))`
- **THEN** the `SpecResult.validation_passed` is `True`
- **AND** the workspace contains `changes/add-session-replay/proposal.md`, `tasks.md`, and `specs/replay/spec.md`
- **AND** every `## ADDED Requirements` block has at least one `### Requirement:` with at least one `#### Scenario:`

#### Scenario: Validation failure surfaces diagnostics without raising

- **GIVEN** a MetaSpecifier whose `LLMClient` returns a `ProposalDoc` missing scenarios
- **WHEN** the agent runs
- **THEN** `SpecResult.validation_passed` is `False`
- **AND** `SpecResult.diagnostics` is non-empty with at least one `ERROR` severity
- **AND** the agent returns `AgentResult.ok` (the operation completed; the spec itself failed)

#### Scenario: Missing LLMClient falls back to deterministic template

- **GIVEN** a MetaSpecifier constructed with `llm_client=None`
- **WHEN** the agent runs with any `SpecGoal`
- **THEN** the returned `ProposalDoc` is a template stub whose structure is valid OpenSpec markdown
- **AND** no network call is attempted

### Requirement: render_proposal is a pure, deterministic markdown renderer

The system SHALL provide `render_proposal(doc: ProposalDoc) -> Mapping[str, str]` that maps file-relative paths to their markdown contents.

#### Scenario: Rendering is idempotent

- **GIVEN** any `ProposalDoc` `d`
- **WHEN** `render_proposal(d)` is called twice
- **THEN** the two outputs are byte-equal

#### Scenario: Rendered markdown is structurally valid OpenSpec

- **GIVEN** a non-trivial `ProposalDoc`
- **WHEN** rendered
- **THEN** the output includes `proposal.md` and `tasks.md` at the top level
- **AND** each `CapabilityDelta` produces `specs/<capability>/spec.md`
- **AND** each spec file starts with `# <capability> capability` and contains `## ADDED Requirements`

### Requirement: self_spec DAG closes the generate → validate → audit loop

The system SHALL provide `create_self_spec_dag()` returning a DAG that executes MetaSpecifier, `openspec_validate`, and MetaAuditor in sequence with context propagation.

#### Scenario: End-to-end execution produces an audit entry

- **GIVEN** a meta-executor built with an `OpenSpecRuntime`, `OpenSpecWorkspace`, `AuditTrail`, and a MetaSpecifier
- **WHEN** the self_spec DAG runs with a valid SpecGoal
- **THEN** the final context contains a `validation_report` key with `passed=True`
- **AND** the audit trail contains at least one `AuditEntry` produced by MetaAuditor

## Invariants

- `ProposalDoc.capabilities` is non-empty; every capability has at least one requirement; every requirement has at least one scenario.
- The workspace writes performed by MetaSpecifier go through `OpenSpecWorkspace.write_change`; MetaSpecifier never touches the filesystem directly.
- MetaSpecifier never writes outside the configured workspace root.
- The repair loop executes at most `max_retries` attempts (default 1); unbounded retries are forbidden.

## Out of Scope

- Archival workflow (`openspec archive`) — future change.
- Human approval UI — out of scope; promotion is a CLI step today.
- Auto-synthesis from spec to code — that's MetaSynthesizer's job, composed downstream.
- Writing to the repo's `openspec/` at runtime — MetaSpecifier's workspace MUST be a meta-owned scratch dir, not the repo's authored specs.
