# meta-scaffolder capability

## ADDED Requirements

### Requirement: MetaScaffolder produces a runnable CEMAF-based app on disk

The system SHALL provide a MetaScaffolder agent that consumes a ScaffoldGoal
(ProposalDoc + generated agent source strings + project name + target directory)
and emits a complete, importable Python package under `target_dir/project_name/`.

#### Scenario: Happy path — generated app is importable and runnable

- **GIVEN** a MetaScaffolder bound to a temp target directory
- **AND** a ScaffoldGoal with a valid ProposalDoc and one generated agent source
- **WHEN** the agent runs
- **THEN** `ScaffoldResult.project_root` is a directory containing `pyproject.toml`, `src/<module>/__init__.py`, `src/<module>/agents.py`, `src/<module>/dags.py`, `src/<module>/bootstrap.py`, and `tests/test_smoke.py`
- **AND** the generated `bootstrap.py` registers the agent with an AgentRegistry and returns a DAGExecutor
- **AND** `importlib.import_module(module)` loads the package without error
- **AND** the package's `bootstrap.create_app_executor()` returns a DAGExecutor

#### Scenario: Refuses to overwrite non-empty target directory

- **GIVEN** a MetaScaffolder and a target_dir that already contains files under `project_name/`
- **WHEN** the agent runs without `overwrite=True`
- **THEN** `AgentResult.success` is `False`
- **AND** `AgentResult.error` mentions the conflict
- **AND** the existing directory is untouched

#### Scenario: Rejects invalid module names

- **GIVEN** a ScaffoldGoal with `project_name="123-weird"` (not a valid Python identifier)
- **WHEN** the agent runs
- **THEN** `AgentResult.success` is `False`
- **AND** the error message explains the naming rule

#### Scenario: Never writes outside target_dir

- **GIVEN** a ScaffoldGoal with a path-traversal `project_name`
- **WHEN** the agent runs
- **THEN** the agent refuses the operation with an explicit error
- **AND** no files are written anywhere

### Requirement: render_project is a pure, deterministic renderer

The system SHALL provide `render_project(skeleton: ProjectSkeleton) -> Mapping[str, str]`
mapping relative paths to file contents.

#### Scenario: Rendering is idempotent

- **GIVEN** a ProjectSkeleton `s`
- **WHEN** `render_project(s)` is called twice
- **THEN** the two outputs are byte-equal

#### Scenario: pyproject pins cemaf and declares the package

- **GIVEN** a ProjectSkeleton with `module_name="my_app"`
- **WHEN** rendered
- **THEN** the `pyproject.toml` content contains `name = "my_app"`
- **AND** lists `cemaf` as a dependency

### Requirement: app_synthesis DAG chains Specifier → Architect → Synthesizer → Scaffolder

The system SHALL provide `create_app_synthesis_dag(target_dir)` producing a DAG
that executes the four meta-agents in order, with context propagation.

#### Scenario: End-to-end app synthesis produces a working project

- **GIVEN** a meta-executor with all four meta-agents registered and a writable target_dir
- **WHEN** the app_synthesis DAG runs with a SpecGoal (feature description)
- **THEN** the final context contains `scaffold_result` with a non-empty `written_files` tuple
- **AND** the resulting project at `scaffold_result.project_root` imports successfully

## Invariants

- MetaScaffolder writes only under `target_dir/project_name/`. Any attempted
  write outside MUST raise and abort.
- `project_name` MUST be a valid Python identifier; non-identifiers are rejected
  at the agent boundary, not discovered at import time.
- `render_project` MUST be a pure function — no I/O, no randomness, no clock reads.
- Overwriting a non-empty existing project directory requires explicit
  `overwrite=True` on the goal; the default MUST be refuse-and-error.
- The scaffolder depends on no template engine and no cookiecutter — pure
  Python string formatting keeps generated apps self-contained.

## Out of Scope

- Git initialization — the scaffolder emits files, not a repo.
- Virtualenv creation or `uv sync` — caller decides when to materialize the
  environment.
- Running the generated tests — smoke testing is the integration test's job,
  not the scaffolder's.
- Multi-package monorepos — one package per scaffold.
