# CEMAF V3 Release Evidence

Verified on 2026-07-04 America/Costa_Rica against branch
`drchinca/CMF-00/freemium_defaults`.

This page maps the v3 readiness checklist to concrete evidence. It is not a
marketing page; it is the receipt drawer. Slightly less glamorous, much harder
to fake.

## Public Release

| Field | Evidence |
|---|---|
| Package version | `pyproject.toml` declares `3.0.0`; `uv.lock` matches. |
| Python support | `requires-python = ">=3.14"`; CI installs Python 3.14. |
| Package build | `uv build --out-dir /tmp/cemaf-v3-build-check` produced `cemaf-3.0.0.tar.gz` and `cemaf-3.0.0-py3-none-any.whl`. |
| Wheel smoke | Fresh Python 3.14 venv installed the built wheel, imported `cemaf`, asserted `__version__ == "3.0.0"`, constructed `AgentRegistry`, `Context`, `DAG`, `RuntimeServices`, and `create_executor()`, and ran `cemaf --help`. |
| Typed package | Wheel contains `cemaf/py.typed`; `pyproject.toml` declares `Typing :: Typed`. |

## Readiness Matrix

| ID | Requirement | Current Evidence |
|---|---|---|
| REQ-01 | CEMAF presents as a protocol-first context engineering framework. | README at-a-glance, README patterns table, `pyproject.toml` description, and `docs/README.md` all use the context-engineering/substrate framing. |
| REQ-02 | CEMAF is a composition root for multi-agent execution. | README and docs lead with `create_executor(...)`, `RuntimeServices`, `DAG`, `Node`, and `Edge`; `make check` confirms documented imports and graph data. |
| REQ-03 | Defaults are local/free-first. | `.env.example` uses `CEMAF_LLM_PROVIDER=ollama`; default embeddings are hash-based; catalog backend defaults to static; paid/hosted providers are explicit extras and env choices. |
| REQ-04 | Paid or hosted providers are not defaults. | Paid-provider-default scan returned no matches; `check_release_package.py` blocks hosted providers in core dependencies and verifies local-first optional extras. |
| REQ-05 | No skipped tests. | `uv run --frozen pytest -q -rs` reported `4067 passed`; skip-pattern scan over `tests src examples pyproject.toml` returned no matches. |
| REQ-06 | Public protocol boundaries stay available. | `make check`, `check_doc_imports.py`, and full tests cover public imports for LLMs, embeddings, vector stores, memory, event buses, selectors, evaluators, `RuntimeServices`, and `cemaf.session.v1`. |
| REQ-07 | Examples run offline unless explicitly marked local-daemon. | `examples/README.md` states listed examples run offline; `tests/integration/test_examples_smoke.py` guards them; direct smokes passed for `hello_world.py`, `session_snapshot.py`, `composed_engine.py`, and `release_engine.py --dry-run`. |
| REQ-08 | Docs voice is senior, human, and non-sycophantic. | `docs/writing_style.md` defines the voice; `check_doc_voice.py` scans 107 Markdown files and passed. |
| REQ-09 | Direct external comparison/vendor lesson labels are absent. | `check_release_naming.py` passed across 917 files; raw forbidden-name scan returned no matches. |
| REQ-10 | Operator/run visibility is a public contract. | `cemaf.session.v1` exists in `src/cemaf/operator`; `check_loop_ops.py` verifies snapshot models, golden fixture, docs, tests, and a tiny runtime path. |
| REQ-11 | Failure-feedback and self-improvement loops remain wired. | `check_loop_ops.py` executes a tiny `IterationLoop` and `SelfImprovementLoop` path through public APIs. |
| REQ-12 | Generated docs imports resolve. | `check_doc_imports.py` scanned 94 Markdown files, 328 unique `from cemaf...` imports, 550 total occurrences, 0 failures. |
| REQ-13 | Architecture graph and trace demo are synchronized. | `make check` verified `cemaf-graph.html` graph data and 7 inlined trace JSONs. |
| REQ-14 | Package metadata and docs agree. | `check_release_package.py` passed for `3.0.0`; CI runs the same checker. |
| REQ-15 | Full release gate is green. | `make check`, docs import check, full pytest, release scans, lock check, build, wheel metadata check, and wheel smoke all passed in the current pass. |

## Commands And Results

| Command | Result |
|---|---|
| `make check` | Passed; includes lint, format check, mypy, doc links, graph data, trace data, voice, release naming, loop/operator, and package audits. |
| `uv run --frozen python docs/architecture/scripts/check_doc_imports.py` | Passed: 94 Markdown files, 328 unique imports, 550 occurrences, 0 failures. |
| `uv run --frozen pytest -q -rs` | Passed: 4067 passed, no skips reported. |
| `uv build --out-dir /tmp/cemaf-v3-build-check` | Passed: built sdist and wheel for `3.0.0`. |
| Fresh wheel install smoke | Passed in `/tmp/cemaf-v3-wheel-smoke` with Python 3.14. |
| Skip marker scan | No matches. |
| Forbidden comparison/vendor scan | No matches. |
| Paid-provider-default scan | No matches. |
| `git diff --check` | Passed. |
| `uv lock --check` | Passed. |

## Publication Boundary

The repository is verified as final package version `3.0.0`. The remaining
publication steps are operational, not framework behavior:

- tag the verified commit as `v3.0.0`;
- create the GitHub release;
- let the PyPI trusted-publishing workflow publish the already-verified package
  shape.

Those steps happen outside the repository state. The repo is ready for them;
the package index can now have its paperwork.
