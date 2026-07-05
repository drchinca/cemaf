# Doc Import Drift

`docs/architecture/scripts/check_doc_imports.py` runs every `from cemaf...`
import statement found inside fenced Python blocks across user-facing markdown
and verifies that it resolves against the local package.

Status as of 2026-07-04:

```text
Scanned 91 markdown files
  unique 'from cemaf...' imports: 324
  total occurrences:              536
  failures:                       0
All documented `from cemaf...` imports resolve.
```

Re-run any time:

```bash
uv run python docs/architecture/scripts/check_doc_imports.py
```

## Maintenance

- Keep this checker green when changing public docs.
- If a doc describes a deferred capability, mark it as not shipped and do not
  include fenced Python imports for packages or names that are absent from
  `src/cemaf`.
- Once this checker is wired into CI, keep it as a hard gate for user-facing
  markdown.
