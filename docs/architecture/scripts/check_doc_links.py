"""Verify every internal markdown link + anchor across the repo's docs.

Walks `README.md`, all top-level user-facing `.md` files, and everything under
`docs/`. For each `[label](target)` link found *outside* fenced code blocks and
inline code spans:

- If the target is a relative path, the file must exist.
- If the target carries an `#anchor`, the target's markdown must contain a
  heading whose GitHub-slug matches the anchor.

External URLs (http/https/mailto) are skipped — link rot for those is a
different problem.

Exit non-zero if any link is broken so this can be wired into CI later.

Usage:
    uv run python docs/architecture/scripts/check_doc_links.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Top-level user-facing docs
TOP_LEVEL = [
    "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "HOW_TO_USE.md",
    "CLAUDE.md", "OPEN.md", "CODE_OF_CONDUCT.md",
]


def gh_anchor(heading: str) -> str:
    """GitHub-style slug: lower, drop punctuation, spaces→dash (one per space)."""
    s = heading.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    return s.replace(" ", "-")


def headings_of(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        gh_anchor(m.group(1))
        for m in re.finditer(r"^#+\s+(.+?)\s*$", text, re.M)
    }


def strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans so Python `[X](Y)` snippets
    don't masquerade as markdown links."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


def collect_md_files() -> list[Path]:
    files = [REPO_ROOT / p for p in TOP_LEVEL]
    for dp, _, fs in os.walk(REPO_ROOT / "docs"):
        for f in fs:
            if f.endswith(".md"):
                files.append(Path(dp) / f)
    return [f for f in files if f.exists()]


def audit() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    broken_file: list[tuple[str, str, str]] = []
    broken_anchor: list[tuple[str, str, str]] = []
    for src in collect_md_files():
        text = src.read_text(encoding="utf-8", errors="replace")
        cleaned = strip_code(text)
        for m in re.finditer(r"\[([^\]\n]+)\]\(([^)\n]+)\)", cleaned):
            link = m.group(2).strip()
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            rel_src = str(src.relative_to(REPO_ROOT))
            if link.startswith("#"):
                if link[1:] not in headings_of(src):
                    broken_anchor.append((rel_src, link, "(self)"))
                continue
            path, _, anchor = link.partition("#")
            if not path:
                continue
            target = (src.parent / path).resolve()
            if not target.exists():
                broken_file.append((rel_src, link, str(target.relative_to(REPO_ROOT)) if target.is_relative_to(REPO_ROOT) else str(target)))
                continue
            if anchor and target.suffix == ".md":
                if anchor not in headings_of(target):
                    broken_anchor.append((rel_src, link, str(target.relative_to(REPO_ROOT))))
    return broken_file, broken_anchor


def main() -> int:
    files = collect_md_files()
    bf, ba = audit()
    print(f"Scanned {len(files)} markdown files")
    print(f"  broken file links:   {len(bf)}")
    print(f"  broken anchor links: {len(ba)}")
    for src, link, target in bf:
        print(f"  ✗ file  {src}  →  {link}  (resolved: {target})")
    for src, link, target in ba:
        print(f"  ✗ anch  {src}  →  {link}  (in: {target})")
    if bf or ba:
        return 1
    print("All internal links resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
