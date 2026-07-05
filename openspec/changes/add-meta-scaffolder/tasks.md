# Tasks

## 1. Types

- [x] 1.1 `ScaffoldGoal`: proposal, generated_agents, project_name, target_dir, cemaf_source, overwrite
- [x] 1.2 `ScaffoldResult`: project_root, written_files, module_name
- [x] 1.3 `ProjectSkeleton`: project_name, module_name, title, description, generated_agents, cemaf_source

## 2. Renderer

- [x] 2.1 `render_project(skeleton)` — pure function producing {path: content} map
- [x] 2.2 Rendered pyproject declares cemaf and supports an explicit `cemaf_source`
- [x] 2.3 Generated `bootstrap.py` registers the generated agents with an AgentRegistry and returns a DAGExecutor
- [x] 2.4 Generated `tests/test_smoke.py` imports the package and exercises registry, executor, and DAG construction

## 3. Agent

- [x] 3.1 `MetaScaffolder(Agent[ScaffoldGoal, ScaffoldResult])`
- [x] 3.2 Validates module name (importable identifier, no dots, no reserved words, no stdlib/package collision)
- [x] 3.3 Writes to `target_dir/project_name/` under a per-project lock — refuses to overwrite non-empty dir unless `overwrite=True`
- [x] 3.4 Never writes outside `target_dir`

## 4. DAG + bootstrap

- [x] 4.1 `create_app_synthesis_dag()` — 4-node pipeline with explicit context mappings
- [x] 4.2 Keep output location on `ScaffoldGoal.target_dir`; no runtime-global scaffold directory
- [x] 4.3 `register_meta_scaffolder()` + wiring in `create_meta_executor()`

## 5. Tests

- [x] 5.1 Contract: ScaffoldGoal/Result shape, Agent protocol
- [x] 5.2 Unit: render_project produces expected file map for a minimal skeleton
- [x] 5.3 Unit: MetaScaffolder writes files, rejects path traversal, rejects invalid module names, bounds descriptions, and serializes concurrent writes
- [x] 5.4 Integration: scaffold a project, then **importlib-load it**, instantiate a generated agent, run it
- [x] 5.5 Integration: app_synthesis DAG end-to-end — feature/app inputs → working app on disk
