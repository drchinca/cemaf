# Add MetaScaffolder — CEMAF generates runnable CEMAF-based apps

## Why

CEMAF's self-hosting layer can design DAGs (MetaArchitect), write specs
(MetaSpecifier), and generate individual agent classes (MetaSynthesizer). What
it cannot do is **assemble those artifacts into a runnable project**. The
missing piece is a scaffolder: take a spec + a set of synthesized agents and
emit a complete CEMAF-based app on disk that imports, type-checks, and runs.

With MetaScaffolder plus the `app_synthesis` DAG, one instruction — *"build an
app that does X"* — turns into a working CEMAF app with a package, a DAG, agents,
tests, and a runnable entry point. The "CEMAF uses CEMAF to build CEMAF-based
apps" thesis stops being hypothetical.

## What Changes

- **Add `cemaf.meta.scaffolder.MetaScaffolder`** — agent consuming a `ScaffoldGoal`
  (ProposalDoc + generated agent sources + project name) and returning a
  `ScaffoldResult` (list of written file paths, project root).
- **Add `cemaf.meta.scaffolder.ProjectSkeleton`** — typed Pydantic representation of
  a scaffolded app (pyproject, package modules, agent sources, DAG source,
  bootstrap, tests, README).
- **Add `render_project(skeleton: ProjectSkeleton) -> Mapping[str, str]`** —
  pure-function renderer producing a relative-path→content map.
- **Add `create_app_synthesis_dag()`** — end-to-end pipeline:
  MetaSpecifier → MetaArchitect → MetaSynthesizer → MetaScaffolder.
- **Extend `create_meta_executor()`** to register MetaScaffolder. The output
  directory is supplied per run through `ScaffoldGoal.target_dir`, keeping the
  agent stateless.

## Impact

- **Affected specs**: `meta-scaffolder` (new)
- **Affected code**: `src/cemaf/meta/scaffolder.py` (new), `src/cemaf/meta/goals.py`
  (added types), `src/cemaf/meta/dags.py` (added DAG factory),
  `src/cemaf/meta/bootstrap.py` + `registry.py` (registration)
- **Not affected**: base framework. Same one-way dependency as MetaSpecifier —
  scaffolder imports from cemaf, the reverse never happens.
- **External deps**: none. No cookiecutter, no Jinja. Pure Python f-string
  templates to keep the generated app self-contained.
