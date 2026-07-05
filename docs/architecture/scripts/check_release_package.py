"""Check release-facing package metadata and install promises."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPECTED_VERSION = "3.0.1"
EXPECTED_STATUS = "Development Status :: 5 - Production/Stable"

HOSTED_CORE_DEPS = (
    "openai",
    "anthropic",
    "huggingface_hub",
    "pinecone-client",
    "asyncpg",
    "pgvector",
    "redis",
)


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _load_pyproject() -> dict[str, Any]:
    return tomllib.loads(_read("pyproject.toml"))


def _dep_names(deps: list[str]) -> set[str]:
    names: set[str] = set()
    for dep in deps:
        match = re.match(r"([A-Za-z0-9_.-]+)", dep)
        if match:
            names.add(match.group(1).lower())
    return names


def _require_contains(failures: list[str], rel_path: str, needle: str) -> None:
    if needle not in _read(rel_path):
        failures.append(f"{rel_path}: missing {needle!r}")


def _check_pyproject(failures: list[str]) -> None:
    data = _load_pyproject()
    project = data["project"]
    optional = project.get("optional-dependencies", {})

    if project.get("name") != "cemaf":
        failures.append("pyproject project.name must be 'cemaf'")
    if project.get("version") != EXPECTED_VERSION:
        failures.append(f"pyproject version must be {EXPECTED_VERSION}")
    if "context engineering" not in project.get("description", "").lower():
        failures.append("pyproject description must position CEMAF around context engineering")
    if project.get("requires-python") != ">=3.14":
        failures.append("pyproject requires-python must stay aligned with the CI Python version")
    if EXPECTED_STATUS not in project.get("classifiers", ()):
        failures.append(f"pyproject classifiers must include {EXPECTED_STATUS!r}")
    if "Typing :: Typed" not in project.get("classifiers", ()):
        failures.append("pyproject classifiers must include 'Typing :: Typed'")
    if not (ROOT / "src/cemaf/py.typed").is_file():
        failures.append("src/cemaf/py.typed is required for the typed package classifier")

    core_deps = _dep_names(project.get("dependencies", []))
    forbidden_core = sorted(dep for dep in HOSTED_CORE_DEPS if dep in core_deps)
    if forbidden_core:
        failures.append(f"core dependencies must stay local/free-first; found hosted deps: {forbidden_core}")

    for extra in ("http", "ollama", "openai-compatible", "gemini", "groq", "together"):
        deps = _dep_names(optional.get(extra, []))
        if "httpx" not in deps:
            failures.append(f"extra {extra!r} must include httpx")

    all_deps = _dep_names(optional.get("all", []))
    for required in ("httpx", "openai", "anthropic", "huggingface_hub"):
        if required not in all_deps:
            failures.append(f"extra 'all' must include {required}")

    scripts = project.get("scripts", {})
    if scripts.get("cemaf") != "cemaf.cli:main":
        failures.append("pyproject [project.scripts] must expose cemaf = cemaf.cli:main")

    wheel = data.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {})
    if wheel.get("packages") != ["src/cemaf"]:
        failures.append("wheel target must package src/cemaf")


def _check_release_docs(failures: list[str]) -> None:
    for rel_path in ("README.md", "CHANGELOG.md", "docs/publishing.md", "docs/release_v3_readiness.md"):
        if not (ROOT / rel_path).is_file():
            failures.append(f"missing release doc: {rel_path}")

    _require_contains(failures, "CHANGELOG.md", f"## [{EXPECTED_VERSION}]")
    _require_contains(failures, "README.md", "Status-3.0")
    _require_contains(failures, "README.md", "4144 passing")
    _require_contains(failures, "README.md", 'pip install "cemaf[ollama]"')
    _require_contains(failures, "docs/quickstart.md", 'pip install "cemaf[ollama]"')
    _require_contains(failures, "docs/publishing.md", f"Version: `{EXPECTED_VERSION}`")
    _require_contains(failures, "docs/release_v3_readiness.md", "check_release_package.py")

    stale_markers = (
        "0.1.0 Alpha",
        "1,016 passing",
        "2301+ tests",
        "We're in **Alpha**",
    )
    for rel_path in ("README.md", "OPEN.md", "docs/publishing.md"):
        text = _read(rel_path)
        for marker in stale_markers:
            if marker in text:
                failures.append(f"{rel_path}: stale release marker {marker!r}")


def _check_ci(failures: list[str]) -> None:
    ci = _read(".github/workflows/ci.yml")
    for command in (
        "check_doc_voice.py",
        "check_release_naming.py",
        "check_loop_ops.py",
        "check_release_package.py",
    ):
        if command not in ci:
            failures.append(f".github/workflows/ci.yml does not run {command}")

    publish = _read(".github/workflows/publish-to-pypi.yml")
    if "uv build" not in publish:
        failures.append("publish workflow must build distributions with uv build")
    if "pypa/gh-action-pypi-publish" not in publish:
        failures.append("publish workflow must use PyPI trusted publishing action")


def main() -> int:
    failures: list[str] = []
    _check_pyproject(failures)
    _check_release_docs(failures)
    _check_ci(failures)

    if failures:
        print("Release package check failed:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(f"Release package check passed for {EXPECTED_VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
