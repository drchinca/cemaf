# CEMAF V3 Release Readiness

This is the release bar for CEMAF 3.0 as a public open source framework for
context-engineered multi-agent applications.

The point of v3 is not a bigger feature list. The point is a stable execution
substrate with patterns other projects can copy without inheriting a pile of
private assumptions. Private assumptions are where frameworks go to become
haunted houses.

## Release Position

CEMAF 3.0 should present itself as:

- a protocol-first context engineering framework;
- a composition root for multi-agent execution;
- a local-first substrate for LLM, retrieval, memory, eval, moderation,
  citation, replay, and observability;
- a catalog of reusable engineering patterns, not app-specific orchestration;
- a framework that lets consuming applications bring their domain agents,
  tools, stores, policies, and UI.

## Non-Negotiables

- **Local-first defaults.** Default LLM path is Ollama, default embeddings are
  hash-based, and default catalog metadata is static. Paid or hosted providers
  require explicit opt-in.
- **No skipped tests.** A skipped test is either removed, fixed, or rewritten as
  an offline contract test.
- **No ghost code.** A factory argument, settings field, adapter method, or
  service hook must either affect behavior, be a documented protocol extension
  point, or be removed.
- **Protocol boundaries stay public.** LLM clients, vector stores, embedding
  providers, memory stores, moderation gates, event buses, selectors, and
  evaluators remain structural protocols.
- **Examples run offline.** Public examples cannot require paid credentials to
  prove the framework shape.
- **Docs use the CEMAF voice.** Senior engineering voice, human enough to be
  readable, specific enough to be useful, and allergic to launch-copy fog.

## Patterns To Lead With

These are the patterns that should define CEMAF in the v3 README, docs, and
examples:

- `RuntimeServices` as the composition root for cross-cutting behavior.
- `Context` + `ContextPatch` + provenance instead of rolling prompt strings.
- `DAG`, `Node`, and `Edge` as the execution contract.
- `EventBus`, `RunLogger`, replay, and operator snapshots for run visibility.
- Eval, moderation, citation, collision, resilience, and recovery as framework
  services, not app-level afterthoughts.
- BYO-X protocols for LLMs, embeddings, vector stores, memory, tools, agents,
  and policies.
- Local-first provider defaults with explicit hosted-provider opt-in.

## Required Release Gates

Run these before tagging any v3 release:

```bash
make check
uv run python docs/architecture/scripts/check_doc_imports.py
uv run --frozen pytest -q -rs
rg -n "pytest\\.skip|pytestmark = pytest\\.mark\\.skipif|@pytest\\.mark\\.skipif|importorskip|pytest\\.mark\\.skip" tests src examples pyproject.toml
uv run python docs/architecture/scripts/check_release_naming.py
uv run python docs/architecture/scripts/check_loop_ops.py
uv run python docs/architecture/scripts/check_release_package.py
uv run python docs/architecture/scripts/check_release_evidence.py
uv build
```

The first three commands must pass. The skip scan must return no matches, and
the release naming, loop/operator, package, and build checks must pass.

## Documentation Gate

`make check` includes `audit-voice`, which runs:

```bash
uv run python docs/architecture/scripts/check_doc_voice.py
```

The check blocks public Markdown that uses hype phrases or sycophantic
language. It does not require dry writing. It requires earned claims. There is
a difference; reviewers are expected to notice it.

`make check` also includes `audit-release-naming`, which blocks public files
from referring to external vendors or comparison repos as the source of CEMAF's
direction. We can learn privately. We do not need to leave the receipt taped to
the front door.

`make check` also includes `audit-loop-ops`, which verifies the public
`cemaf.session.v1`, failure-feedback, and self-improvement surfaces still have
code, docs, examples, tests, and golden fixtures behind them. V3 can have sharp
edges; it cannot have cardboard doors.

`make check` also includes `audit-package`, which verifies v3 package metadata,
typed-package markers, local-first optional extras, CI release audits, and
release docs agree with the package version. Version drift is a bug wearing a
calendar.

`make check` also includes `audit-release-evidence`, which verifies
[V3 Release Evidence](release_v3_evidence.md) covers each release requirement,
the command results, and the remaining human release decision.

## Release Candidate Checklist

- README states the framework boundary clearly: substrate, not application.
- README quick start works with local/free defaults.
- Package metadata is `3.0.1`, and the changelog has the matching section.
- `.env.example` does not default to paid or hosted providers.
- `examples/README.md` identifies offline examples first.
- Every public factory with `settings=` consumes settings or documents an
  extension point.
- New provider adapters include offline unit tests and opt-in integration tests.
- Generated docs imports resolve.
- Architecture graph is regenerated after source changes.
- Public docs avoid the banned voice phrases checked by `audit-voice`.
- Full test suite passes with `-rs` and reports no skips.
- [V3 Release Evidence](release_v3_evidence.md) maps every requirement to
  current proof.
