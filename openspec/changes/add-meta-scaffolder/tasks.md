# Tasks

## 1. Types

- [ ] 1.1 `ScaffoldGoal`: proposal, generated_agents (tuple of agent source strings), project_name, target_dir
- [ ] 1.2 `ScaffoldResult`: project_root (Path), written_files (tuple[str, ...]), module_name
- [ ] 1.3 `ProjectSkeleton`: project_name, module_name, pyproject, package_files (dict), test_files (dict), readme

## 2. Renderer

- [ ] 2.1 `render_project(skeleton)` — pure function producing {path: content} map
- [ ] 2.2 Rendered pyproject pins cemaf and declares the package entrypoint
- [ ] 2.3 Generated `bootstrap.py` registers the generated agents with an AgentRegistry and returns a DAGExecutor
- [ ] 2.4 Generated `tests/test_smoke.py` imports the package and instantiates the registered agents

## 3. Agent

- [ ] 3.1 `MetaScaffolder(Agent[ScaffoldGoal, ScaffoldResult])`
- [ ] 3.2 Validates module name (importable identifier, no dots, no reserved words)
- [ ] 3.3 Writes atomically to `target_dir/project_name/` — refuses to overwrite non-empty dir unless `overwrite=True`
- [ ] 3.4 Never writes outside `target_dir`

## 4. DAG + bootstrap

- [ ] 4.1 `create_app_synthesis_dag(target_dir: Path)` — 4-node pipeline
- [ ] 4.2 `MetaServices.scaffold_output_dir: Path | None`
- [ ] 4.3 `register_meta_scaffolder()` + wiring in `create_meta_executor()`

## 5. Tests

- [ ] 5.1 Contract: ScaffoldGoal/Result shape, Agent protocol
- [ ] 5.2 Unit: render_project produces expected file map for a minimal skeleton
- [ ] 5.3 Unit: MetaScaffolder writes files, rejects path traversal, rejects invalid module names
- [ ] 5.4 Integration: scaffold a project, then **importlib-load it**, instantiate a generated agent, run it
- [ ] 5.5 Integration: app_synthesis DAG end-to-end — feature description → working app on disk
