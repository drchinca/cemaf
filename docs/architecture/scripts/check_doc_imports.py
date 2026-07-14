"""Statically verify docs `from cemaf...` imports against `src/cemaf` exports.

This checker does not import project runtime modules, so it works even when
optional dependencies are missing. It resolves modules to files under `src/`,
builds a best-effort export set from AST, and validates imported symbols.
"""

from __future__ import annotations

import argparse
import ast
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"

TOP_LEVEL = [
    "README.md",
    "CONTRIBUTING.md",
    "HOW_TO_USE.md",
    "AGENTS.md",
]

PLACEHOLDER_NAMES = {"...", "MyAgent", "MyTool", "MyTask", "YourAgent", "YourTool"}


@dataclass
class ImportLine:
    path: str
    line_no: int
    statement: str


def collect_files(excluded_paths: set[str] | None = None) -> list[Path]:
    excluded_paths = excluded_paths or set()
    files = [REPO_ROOT / p for p in TOP_LEVEL]
    for dp, _, fs in os.walk(REPO_ROOT / "docs"):
        for f in fs:
            if f.endswith(".md"):
                files.append(Path(dp) / f)

    out: list[Path] = []
    for f in files:
        if not f.exists():
            continue
        rel = str(f.relative_to(REPO_ROOT))
        if rel in excluded_paths:
            continue
        out.append(f)
    return out


def extract_imports(path: Path) -> list[ImportLine]:
    out: list[ImportLine] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    in_py = False

    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            fence_spec = stripped[3:].strip().lower()
            if in_py:
                in_py = False
            else:
                in_py = fence_spec == "python" or fence_spec == "py" or fence_spec.startswith("python ")
            continue
        if not in_py:
            continue
        if not stripped.startswith("from cemaf"):
            continue
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            continue
        if not (tree.body and isinstance(tree.body[0], ast.ImportFrom)):
            continue
        names = [alias.name for alias in tree.body[0].names]
        if any(name in PLACEHOLDER_NAMES for name in names):
            continue
        out.append(ImportLine(path=str(path.relative_to(REPO_ROOT)), line_no=i, statement=stripped))
    return out


def _module_to_file(module: str) -> Path | None:
    if not module.startswith("cemaf"):
        return None
    parts = module.split(".")
    mod_file = SRC_ROOT.joinpath(*parts).with_suffix(".py")
    if mod_file.exists():
        return mod_file
    pkg_init = SRC_ROOT.joinpath(*parts, "__init__.py")
    if pkg_init.exists():
        return pkg_init
    return None


def _parse_string_sequence(node: ast.AST) -> set[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: set[str] = set()
    for elt in node.elts:
        if not (isinstance(elt, ast.Constant) and isinstance(elt.value, str)):
            return None
        values.add(elt.value)
    return values


_EXPORT_CACHE: dict[str, tuple[set[str], str] | None] = {}


def _exports_for_module(module: str) -> tuple[set[str], str] | None:
    cached = _EXPORT_CACHE.get(module)
    if cached is not None or module in _EXPORT_CACHE:
        return cached

    module_path = _module_to_file(module)
    if module_path is None:
        _EXPORT_CACHE[module] = None
        return None

    text = module_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        _EXPORT_CACHE[module] = (set(), str(module_path))
        return _EXPORT_CACHE[module]

    names: set[str] = set()
    explicit_all: set[str] | None = None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
            continue
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name)
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                    if target.id == "__all__":
                        parsed = _parse_string_sequence(node.value)
                        if parsed is not None:
                            explicit_all = parsed
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
            if node.target.id == "__all__" and node.value is not None:
                parsed = _parse_string_sequence(node.value)
                if parsed is not None:
                    explicit_all = parsed

    exports = explicit_all if explicit_all is not None else names
    _EXPORT_CACHE[module] = (exports, str(module_path))
    return _EXPORT_CACHE[module]


def verify(stmt: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(stmt)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg}"
    if not tree.body or not isinstance(tree.body[0], ast.ImportFrom):
        return False, "not an import statement"

    import_node = tree.body[0]
    module = import_node.module
    if not module:
        return False, "relative imports unsupported"

    resolved = _exports_for_module(module)
    if resolved is None:
        return False, f"ModuleNotFoundError: No module named '{module}'"
    exports, module_path = resolved
    if not exports:
        return False, f"ImportError: unable to resolve exports in '{module_path}'"

    for alias in import_node.names:
        if alias.name == "*":
            continue
        if alias.name not in exports:
            return False, f"ImportError: cannot import name '{alias.name}' from '{module}' ({module_path})"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Repo-relative markdown path to exclude from import checks (repeatable).",
    )
    args = parser.parse_args()

    files = collect_files(set(args.exclude))
    all_imports: list[ImportLine] = []
    for f in files:
        all_imports.extend(extract_imports(f))

    if not all_imports:
        print("No `from cemaf...` imports found in docs.")
        return 0

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
    raise SystemExit(main())
