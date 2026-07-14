"""Check Markdown for public-documentation hype and sycophantic phrasing."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

SCAN_ROOTS = tuple(ROOT.glob("*.md")) + (
    ROOT / "docs",
    ROOT / "examples",
    ROOT / "openspec",
)

BANNED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        ("amazing", r"\bamazing\b"),
        ("awesome", r"\bawesome\b"),
        ("incredible", r"\bincredible\b"),
        ("revolutionary", r"\brevolutionary\b"),
        ("game-changing", r"\bgame[- ]changing\b"),
        ("magical", r"\bmagical\b"),
        ("effortless", r"\beffortless\b"),
        ("seamless", r"\bseamless(?:ly)?\b"),
        ("best-in-class", r"\bbest[- ]in[- ]class\b"),
        ("world-class", r"\bworld[- ]class\b"),
        ("state-of-the-art", r"\bstate[- ]of[- ]the[- ]art\b"),
        ("enterprise-grade", r"\benterprise[- ]grade\b"),
        ("production-ready", r"\bproduction[- ]ready\b"),
        ("cutting-edge", r"\bcutting[- ]edge\b"),
        ("next-generation", r"\bnext[- ]generation\b"),
        ("next-gen", r"\bnext[- ]gen\b"),
        ("unleash", r"\bunleash\b"),
        ("unlock", r"\bunlock(?:s|ing)?\b"),
        ("empower", r"\bempower(?:ed|s|ing)?\b"),
        ("delight", r"\bdelight(?:ed|ful|s|ing)?\b"),
        ("supercharge", r"\bsupercharge(?:d|s|ing)?\b"),
        ("transform your", r"\btransform your\b"),
        ("we believe", r"\bwe believe\b"),
        ("we are excited", r"\bwe(?:'re| are) excited\b"),
        ("thank you", r"\bthank you\b"),
        ("killer feature", r"\bkiller feature\b"),
        ("we welcome", r"\bwe welcome\b"),
        ("we're here", r"\bwe(?:'re| are) here\b"),
        ("want to contribute", r"\bwant to contribute\b"),
        ("join our community", r"\bjoin our community\b"),
        ("get up and running", r"\bget up and running\b"),
    )
)


def _iter_markdown_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file() and root.suffix == ".md":
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*.md") if path.is_file())
    return sorted(set(files))


def _strip_fenced_code(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            lines.append("")
            continue
        lines.append("" if in_fence else line)
    return "\n".join(lines)


def main() -> int:
    failures: list[str] = []
    for path in _iter_markdown_files():
        text = _strip_fenced_code(path.read_text(encoding="utf-8"))
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in BANNED_PATTERNS:
                if pattern.search(line):
                    rel = path.relative_to(ROOT)
                    failures.append(f"{rel}:{line_no}: banned docs voice phrase '{label}': {line.strip()}")

    if failures:
        print("Markdown voice check failed:")
        for failure in failures:
            print(f"  {failure}")
        print("\nUse specific, earned claims with a human engineering voice. See docs/writing_style.md.")
        return 1

    print(f"Markdown voice check passed for {len(_iter_markdown_files())} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
