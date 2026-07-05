# MetaScaffolder — Post-Review Fix Plan

Multi-agent review of Phase A (commits `83285d5` and earlier) surfaced contract
bugs in the generated code. The generated CEMAF-app looks correct structurally
but breaks on first real use. This document is the fix plan.

## Reviewers

- **solutions-architect**: architecture, coupling, spec drift, concurrency
- **senior-python**: code quality, TOML injection, dependency resolution, subprocess patterns
- **qa-agent**: spec coverage, missing tests, edge cases
- **junior-developer**: fresh eyes, readability, "does it actually run?"

## Findings Ranked

### P0 — Contract bugs that break the headline claim

| # | Finding | Reviewer | Fix |
|---|---------|----------|-----|
| 1 | Generated `bootstrap.py` references `{cls}Goal` but never imports it → `NameError` on first use | junior-dev | Pass `GeneratedAgent(class_name, goal_class_name, source)` triples; emit `from pkg.agents import <cls>, <cls>Goal` |
| 2 | `agent_sources` + `agent_class_names` parallel tuples with no alignment guarantee | junior-dev, senior-python | Replace with `GeneratedAgent` typed pair |
| 3 | TOML/Python injection via `description`/`title` — `"` in a string breaks the generated `pyproject.toml` + `dags.py` | senior-python, qa, junior | Use `json.dumps()` for string literal escaping in TOML + Python contexts |
| 4 | `cemaf` dep is bare string in generated `pyproject.toml` — `uv sync` fails (cemaf not on PyPI) | senior-python, junior | Add `cemaf_source: str` to `ScaffoldGoal` with a clear default-source note |
| 5 | Generated `dags.py` imports `NodeID`, `Edge`, `Node` but uses none → ruff fails in generated repo's CI | junior-dev | Drop unused imports |
| 6 | TOCTOU race in `_prepare_root` — two concurrent scaffolds to same target interleave | architect, qa | Per-(target_dir, project_name) `asyncio.Lock` |
| 7 | Spec drift: `create_app_synthesis_dag(target_dir)` per spec, no-arg in impl | architect | Update spec to match reality (target_dir lives on `ScaffoldGoal`, not the DAG factory) |

### P1 — Missing tests from review gaps

| # | Missing test | Reviewer |
|---|---|---|
| 8 | Path traversal via `project_name=".."` or `"a/b"` (spec line 38 unasserted) | qa |
| 9 | TOML injection via description with `"` | senior-python, qa |
| 10 | Concurrent scaffold to same `target_dir/project_name` | architect, qa |
| 11 | stdlib name collision — reject `os`, `sys`, `json`, `typing` | qa, junior |
| 12 | Description boundary — truncation at 200 chars | qa |
| 13 | Mismatched generated_agents vs class_names (obsoleted by fix #2) | qa, junior |

### Deferred to follow-up PR

- **Non-zero-arg agent constructors**: realistic agents take `llm_client` etc. Current generated `bootstrap.py` assumes no-arg `__init__`. Co-design with MetaSynthesizer to emit factories, or document the constraint explicitly. (senior-python, architect)
- **`target_dir: str` → `Path` in ScaffoldGoal**: Pydantic JSON serialization work, cosmetic. (architect)
- **Context-builder node DSL**: app synthesis now runs through explicit node input mappings; a richer transform DSL can be designed separately if needed. (qa)
- **Generated README metadata** (change_id, CEMAF version, spec ref): useful for traceability; renderer stays pure by taking metadata as explicit `ProjectSkeleton` fields. (junior)
- **`GeneratedAgent.from_services(services)` factory pattern**: replaces zero-arg instantiation in generated bootstrap. (senior-python)

## Execution Plan (this PR)

Three focused commits on `drchinca/meta-openspec-mcp/self-spec-loop`:

**Commit X — Fix generated code correctness**
- Add `GeneratedAgent(class_name, goal_class_name, source)` typed model to `meta/goals.py`
- Replace `agent_sources` + `agent_class_names` in `ScaffoldGoal` + `ProjectSkeleton` with `generated_agents: tuple[GeneratedAgent, ...]`
- Update `_render_agents` + `_render_bootstrap` to emit `from pkg.agents import <cls>, <cls>Goal` and register as `registry.register_agent(agent_instance=<cls>(), goal_type=<cls>Goal)`
- Drop unused imports from generated `dags.py`
- Update existing tests

**Commit Y — String escaping + cemaf_source**
- Use `json.dumps()` to escape strings going into TOML basic strings + Python string literals
- Add `cemaf_source: str = ""` to `ScaffoldGoal`; when set, use it in generated `pyproject.toml`; when empty, emit a clear default-source note so users can pin a Git or local source
- Add tests for escape correctness

**Commit Z — Concurrent lock + review-gap tests + spec drift**
- Per-target `asyncio.Lock` on MetaScaffolder instance (keyed by resolved project_root)
- New tests: path traversal via project_name, stdlib collision rejection, TOML injection safety, concurrent scaffold serialization
- Update spec at `openspec/changes/add-meta-scaffolder/specs/meta-scaffolder/spec.md` — `create_app_synthesis_dag()` takes no args; target_dir lives on `ScaffoldGoal`

## Acceptance

All three commits green; pre-commit hooks clean; suite ≥ current count (2652 passed, 1 skipped) + the new tests. After merge, the headline demo — *"CEMAF generates a CEMAF-based app that actually runs"* — is defensible instead of paper.
