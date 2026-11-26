"""Static Python architecture/contract descriptions implementing DocSource."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cemaf.docs_api.index import DocEntry, DocEntryKind


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Subscript):
        return _base_name(base.value)
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


@dataclass(frozen=True)
class PythonContractDocSource:
    """Describe modules, protocols and declared agents/skills without importing code.

    Static declarations are distinct from runtime registrations. Package source
    is explicit, so this adapter also works for a consuming application's code.
    """

    root: Path
    package: str = "cemaf"

    @property
    def name(self) -> str:
        return "python-contracts"

    def load(self) -> Iterable[DocEntry]:
        if not self.root.is_dir():
            raise ValueError("Python contract source must be a package directory")
        modules: dict[str, ast.Module] = {}
        for path in sorted(self.root.rglob("*.py")):
            relative = path.relative_to(self.root).with_suffix("")
            parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
            module = ".".join((self.package, *parts))
            modules[module] = ast.parse(path.read_text(encoding="utf-8"))
        for module, tree in modules.items():
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in modules:
                    imported.add(f"module:{node.module}")
                elif isinstance(node, ast.Import):
                    imported.update(f"module:{alias.name}" for alias in node.names if alias.name in modules)
            yield DocEntry(
                id=f"module:{module}",
                kind=DocEntryKind.MODULE,
                title=module,
                body=ast.get_docstring(tree) or f"Python module `{module}`.",
                source=self.name,
                metadata={"okf_type": "Module", "module": module, "related_ids": sorted(imported)},
            )
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                    continue
                bases = {_base_name(base) for base in node.bases}
                concept_type = next(
                    (name for name in ("Protocol", "Agent", "Skill", "Tool") if name in bases), None
                )
                if concept_type is None:
                    continue
                signatures = []
                for child in node.body:
                    if isinstance(
                        child, (ast.FunctionDef, ast.AsyncFunctionDef)
                    ) and not child.name.startswith("_"):
                        prefix = "async " if isinstance(child, ast.AsyncFunctionDef) else ""
                        returns = f" -> {ast.unparse(child.returns)}" if child.returns else ""
                        signatures.append(f"{prefix}{child.name}({ast.unparse(child.args)}){returns}")
                body = ast.get_docstring(node) or f"{concept_type} `{module}.{node.name}`."
                if signatures:
                    body += "\n\n## Public contract\n\n```python\n" + "\n".join(signatures) + "\n```\n"
                yield DocEntry(
                    id=f"contract:{module}.{node.name}",
                    kind=DocEntryKind.SPEC,
                    title=f"{module}.{node.name}",
                    body=body,
                    source=self.name,
                    metadata={
                        "okf_type": concept_type,
                        "definition_kind": "declaration",
                        "related_ids": [f"module:{module}"],
                        "runtime_checkable": any(
                            _base_name(d) == "runtime_checkable" for d in node.decorator_list
                        ),
                    },
                )
