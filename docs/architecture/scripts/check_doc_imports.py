"""Verify every `from cemaf...` import in user-facing docs actually resolves.

Walks all markdown under `docs/` plus top-level user-facing files. For each
fenced Python code block, extracts every `from cemaf...` import line and
attempts to import it in a subprocess. Lines that produce ImportError or
AttributeError are reported with file:line.

Skips:
- Lines that look like type hints or comments rather than statements.
- Imports whose target identifier is obviously a placeholder (`...`, `MyX`,
  `YourThing`).

Exits 0 when every import resolves; non-zero on any failure. Designed for CI.

Usage:
    uv run python docs/architecture/scripts/check_doc_imports.py
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

TOP_LEVEL = [
    "README.md", "CONTRIBUTING.md", "HOW_TO_USE.md", "AGENTS.md",
]

PLACEHOLDER_NAMES = {"...", "MyAgent", "MyTool", "MyTask", "YourAgent", "YourTool"}


@dataclass
class ImportLine:
    path: str            # repo-relative
    line_no: int
    statement: str       # the literal `from cemaf... import ...` text


def collect_files() -> list[Path]:
    files = [REPO_ROOT / p for p in TOP_LEVEL]
    for dp, _, fs in os.walk(REPO_ROOT / "docs"):
        for f in fs:
            if f.endswith(".md"):
                files.append(Path(dp) / f)
    return [f for f in files if f.exists()]


def extract_imports(path: Path) -> list[ImportLine]:
    """Pull every `from cemaf...` line out of fenced python code blocks."""
    out: list[ImportLine] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    in_py = False
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if line.startswith("```"):
            fence = line.strip("`").strip().lower()
            in_py = bool(fence in {"python", "py"} or (in_py and not fence))
            if not stripped.startswith("```python") and stripped.startswith("```"):
                in_py = (fence in {"python", "py"})
            continue
        if not in_py:
            continue
        if not stripped.startswith("from cemaf"):
            continue
        # parse with ast to confirm it's a real import statement
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            continue
        if not (tree.body and isinstance(tree.body[0], ast.ImportFrom)):
            continue
        names = [a.name for a in tree.body[0].names]
        if any(n in PLACEHOLDER_NAMES for n in names):
            continue
        out.append(
            ImportLine(
                path=str(path.relative_to(REPO_ROOT)),
                line_no=i,
                statement=stripped,
            )
        )
    return out


def verify(stmt: str) -> tuple[bool, str]:
    """Run the import in a child process. Returns (ok, error_msg)."""
    proc = subprocess.run(
        [sys.executable, "-c", stmt],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode == 0:
        return True, ""
    # Last line of stderr is usually the most useful one
    err = (proc.stderr or proc.stdout).strip().splitlines()
    return False, err[-1] if err else "unknown error"


def main() -> int:
    files = collect_files()
    all_imports: list[ImportLine] = []
    for f in files:
        all_imports.extend(extract_imports(f))

    if not all_imports:
        print("No `from cemaf...` imports found in docs.")
        return 0

    # Dedupe by exact statement to avoid re-running identical imports
    by_stmt: dict[str, list[ImportLine]] = {}
    for imp in all_imports:
        by_stmt.setdefault(imp.statement, []).append(imp)

    failures: list[tuple[ImportLine, str]] = []
    for stmt, sites in by_stmt.items():
        ok, err = verify(stmt)
        if not ok:
            for site in sites:
                failures.append((site, err))

    print(f"Scanned {len(files)} markdown files")
    print(f"  unique 'from cemaf...' imports: {len(by_stmt)}")
    print(f"  total occurrences:              {len(all_imports)}")
    print(f"  failures:                       {len(failures)}")
    for site, err in failures:
        print(f"  ✗ {site.path}:{site.line_no}")
        print(f"      {site.statement}")
        print(f"      → {err}")
    if failures:
        return 1
    print("All documented `from cemaf...` imports resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
