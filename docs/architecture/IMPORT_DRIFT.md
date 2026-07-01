# Doc Import Drift — Current Baseline

`docs/architecture/scripts/check_doc_imports.py` statically validates
`from cemaf...` imports in fenced Python snippets against exports under
`src/cemaf`.

## Current status

As of 2026-06-30, the checker passes for all markdown docs:

```bash
python3 docs/architecture/scripts/check_doc_imports.py
```

Expected output shape:

- `failures: 0`
- `All documented 'from cemaf...' imports resolve.`

## Aspirational docs policy

Some docs include future API sketches for modules that are not shipped yet
(for example `offline`, `sync`, and `throttling`). Those snippets should use
commented import lines (for example `# Future API sketch: from cemaf...`) so
strict import verification can remain enabled repository-wide.

## CI wiring

Pre-commit already enforces this check locally via `check-doc-imports`. If you
also add it to CI, use the exact same exclusion list to keep behavior aligned.
