"""Check public files for forbidden direct comparison labels."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

EXCLUDED_DIRS = {
    ".claude",
    ".codex",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "htmlcov",
}

EXCLUDED_FILES = {
    "docs/architecture/cemaf-graph.html",
    "uv.lock",
}

FORBIDDEN_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(re.escape(term), re.IGNORECASE))
    for label, term in (
        ("external comparison name", "".join(("omni", "graph"))),
        ("external organization name", "".join(("modern", "relay"))),
        ("hosted-provider lesson label", "".join(("open", "ai lessons"))),
        ("hosted-provider lesson label", "".join(("gem", "ini lessons"))),
        ("hosted-provider lesson label", "".join(("ver", "tex lessons"))),
        ("fork-comparison phrase", "".join(("lessons ", "from"))),
    )
)


def _iter_public_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    failures: list[str] = []
    scanned = 0
    for path in _iter_public_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        scanned += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in FORBIDDEN_TERMS:
                if pattern.search(line):
                    rel = path.relative_to(ROOT)
                    failures.append(f"{rel}:{line_no}: {label}: {line.strip()}")

    if failures:
        print("Release naming check failed:")
        for failure in failures:
            print(f"  {failure}")
        print("\nAvoid direct upstream/vendor comparison names in public repo text.")
        return 1

    print(f"Release naming check passed for {scanned} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
