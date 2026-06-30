# Benchmark Handoff Notes

This file is a continuation guide for any LLM/engineer picking up benchmark work on CEMAF.

## Current branch context

- Repository: `cemaf`
- Branch: `feat/pypi-ci-benchmarks`
- PR: `#192`
- Goal: strengthen benchmark veracity evidence with real executable checks and local numbers.

## Nomenclature rule

- In benchmark artifacts/docs, avoid the overloaded IAM/IdP wording.
- Use: `veracity_check`, `capability statement`, `factual statement`, `evidence`, `check_id`.

## Files already modified in this pass

- `benchmarks/run_benchmarks.py`
- `benchmarks/README.md`
- `README.md`
- `CLAUDE.md`

## What has been added in `run_benchmarks.py`

- Stronger shared-executor concurrency check:
  - Uses a router DAG and explicit `run_id`s.
  - Verifies route/context isolation and event correlation IDs.
- New veracity checks:
  - Auction selection (`Node.auction` + `DefaultAgentSelector`)
  - Council voting + DAG steering (`Node.council` + JSON_RULE edge)
  - Gate interceptor blocking (`GateEvalInterceptor` + `LengthEvaluator`)
  - Citation tracking/provenance (`CitationTracker` + `create_cited_fact_patch`)
  - Blueprint harvest/search (`create_blueprint_harvester` + `BlueprintLibrary.search`)
  - RLM concurrent query isolation (shared tool, concurrent requests)
- RLM corpus/check hardening:
  - Added decoy fields in corpus sections.
  - Switched to positive available context budget (`max_tokens=2200`, reserved output `1000`).
  - Added wrong-answer leak and coverage metrics.

## Important pending work before commit

1. Fix line-length/style issues in `benchmarks/run_benchmarks.py` (ruff E501).
2. Ensure `run_veracity_checks()` list reflects intended full check set.
3. Run verification:
   - `uv run ruff format benchmarks/run_benchmarks.py`
   - `uv run ruff check benchmarks/run_benchmarks.py`
   - `make benchmark`
   - `make benchmark-report`
   - `make check`
   - optional: `uv run pytest -q`
4. Confirm benchmark terminology in new artifacts and docs.
5. Review generated artifacts:
   - `benchmarks/results/local-baseline.json`
   - `benchmarks/results/local-baseline.md`
6. Update PR #192 summary with new check count and metrics.

## Known review-driven gaps (if continuing beyond current scope)

- Add explicit capability inventory (`covered` / `partial` / `not_checked`) in benchmark report.
- Add reproducibility metadata to report (git SHA, dirty tree, lock hash, args).
- Consider regression thresholds/statistical confidence (currently smoke + repeated samples).
- If needed, improve RLM source-route proof by surfacing chunk/source IDs in tool metadata.

## Fast resume command sequence

```bash
git status --short --branch
uv run ruff format benchmarks/run_benchmarks.py
uv run ruff check benchmarks/run_benchmarks.py
make benchmark-report
make check
```
