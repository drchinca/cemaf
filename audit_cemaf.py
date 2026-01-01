#!/usr/bin/env python3
"""
Comprehensive CEMAF codebase audit.

Checks for:
- Consistency issues
- Outdated references
- Incomplete work
- Missing files
- Configuration completeness
"""

import re
from pathlib import Path
from collections import defaultdict


def check_version_consistency():
    """Check version numbers are consistent across files."""
    print("=" * 60)
    print("VERSION CONSISTENCY CHECK")
    print("=" * 60)

    version_files = {
        "pyproject.toml": None,
        "src/cemaf/__init__.py": None,
        ".env.example": None,
    }

    # Check pyproject.toml
    pyproject = Path("pyproject.toml").read_text()
    version_match = re.search(r'version = "([^"]+)"', pyproject)
    if version_match:
        version_files["pyproject.toml"] = version_match.group(1)

    # Check __init__.py
    init_file = Path("src/cemaf/__init__.py")
    if init_file.exists():
        init_content = init_file.read_text()
        version_match = re.search(r'__version__\s*=\s*"([^"]+)"', init_content)
        if version_match:
            version_files["src/cemaf/__init__.py"] = version_match.group(1)

    # Check .env.example
    env_file = Path(".env.example")
    if env_file.exists():
        env_content = env_file.read_text()
        version_match = re.search(r'CEMAF_VERSION=([^\n]+)', env_content)
        if version_match:
            version_files[".env.example"] = version_match.group(1)

    versions = set(v for v in version_files.values() if v)

    if len(versions) == 1:
        print(f"✅ Version consistent: {versions.pop()}")
    else:
        print("⚠️  Version inconsistencies found:")
        for file, version in version_files.items():
            print(f"   {file}: {version}")

    print()


def check_python_version_references():
    """Check for outdated Python version references."""
    print("=" * 60)
    print("PYTHON VERSION REFERENCES CHECK")
    print("=" * 60)

    issues = []

    # Check for old Python version references in all files
    for pattern in ["**/*.md", "**/*.py", "**/*.toml", "**/*.yaml"]:
        for file in Path(".").glob(pattern):
            if ".venv" in str(file) or "uv.lock" in str(file):
                continue

            content = file.read_text(errors="ignore")

            # Check for 3.11, 3.12, 3.13 references
            for old_version in ["3.11", "3.12", "3.13"]:
                if old_version in content and "3.14" not in content[:content.index(old_version) + 10]:
                    # Skip if it's just a version range like ">=3.11"
                    if f">={old_version}" not in content and f"= {old_version}" in content:
                        issues.append(f"{file}: Contains '{old_version}' reference")

    if not issues:
        print("✅ No outdated Python version references found")
    else:
        print(f"⚠️  Found {len(issues)} potential outdated Python version references:")
        for issue in issues[:10]:  # Show first 10
            print(f"   {issue}")
        if len(issues) > 10:
            print(f"   ... and {len(issues) - 10} more")

    print()


def check_factory_completeness():
    """Check all modules have factories and proper structure."""
    print("=" * 60)
    print("FACTORY COMPLETENESS CHECK")
    print("=" * 60)

    modules_dir = Path("src/cemaf")
    modules = [d for d in modules_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]

    factory_status = {}
    init_status = {}

    for module in modules:
        module_name = module.name

        # Check for factories.py
        factories_file = module / "factories.py"
        has_factories = factories_file.exists()

        # Check if factories.py has create_*_from_config
        has_from_config = False
        if has_factories:
            content = factories_file.read_text()
            has_from_config = "create_" in content and "_from_config" in content

        factory_status[module_name] = {
            "has_factories": has_factories,
            "has_from_config": has_from_config
        }

        # Check __init__.py exports factories
        init_file = module / "__init__.py"
        exports_factories = False
        has_config_docs = False

        if init_file.exists():
            content = init_file.read_text()
            exports_factories = "from cemaf." + module_name + ".factories import" in content
            has_config_docs = "Configuration:" in content

        init_status[module_name] = {
            "exports_factories": exports_factories,
            "has_config_docs": has_config_docs
        }

    # Report
    print(f"Total modules: {len(modules)}")

    missing_factories = [m for m, s in factory_status.items() if not s["has_factories"]]
    if missing_factories:
        print(f"⚠️  Modules missing factories.py ({len(missing_factories)}):")
        for m in missing_factories:
            print(f"   - {m}")
    else:
        print("✅ All modules have factories.py")

    print()

    missing_from_config = [m for m, s in factory_status.items() if s["has_factories"] and not s["has_from_config"]]
    if missing_from_config:
        print(f"⚠️  Factories without create_*_from_config ({len(missing_from_config)}):")
        for m in missing_from_config:
            print(f"   - {m}")

    print()

    no_factory_exports = [m for m, s in init_status.items() if not s["exports_factories"]]
    if no_factory_exports:
        print(f"📋 __init__.py files not exporting factories ({len(no_factory_exports)}):")
        for m in no_factory_exports:
            print(f"   - {m}")

    print()

    no_config_docs = [m for m, s in init_status.items() if not s["has_config_docs"]]
    if no_config_docs:
        print(f"📋 __init__.py files without config documentation ({len(no_config_docs)}):")
        for m in no_config_docs:
            print(f"   - {m}")

    print()


def check_settings_coverage():
    """Check all modules have corresponding Settings classes."""
    print("=" * 60)
    print("SETTINGS COVERAGE CHECK")
    print("=" * 60)

    # Get all Settings classes from config/protocols.py
    protocols_file = Path("src/cemaf/config/protocols.py")
    content = protocols_file.read_text()

    settings_classes = re.findall(r'class (\w+Settings)\(BaseModel\)', content)

    print(f"Found {len(settings_classes)} Settings classes:")
    for cls in sorted(settings_classes):
        module_name = cls.replace("Settings", "").lower()
        print(f"   - {cls} → {module_name}/")

    # Check main Settings class includes all of them
    main_settings_match = re.search(r'class Settings\(BaseModel\):.*?(?=class|\Z)', content, re.DOTALL)
    if main_settings_match:
        main_settings_content = main_settings_match.group(0)

        missing_in_main = []
        for cls in settings_classes:
            if cls != "Settings" and cls.lower() not in main_settings_content.lower():
                missing_in_main.append(cls)

        if missing_in_main:
            print(f"\n⚠️  Settings classes not in main Settings ({len(missing_in_main)}):")
            for cls in missing_in_main:
                print(f"   - {cls}")
        else:
            print("\n✅ All Settings classes included in main Settings")

    print()


def check_todos_and_fixmes():
    """Check for TODO and FIXME comments."""
    print("=" * 60)
    print("TODO/FIXME CHECK")
    print("=" * 60)

    todos = []
    fixmes = []

    for file in Path("src").rglob("*.py"):
        content = file.read_text()

        for i, line in enumerate(content.split('\n'), 1):
            if "TODO" in line:
                todos.append(f"{file}:{i}: {line.strip()}")
            if "FIXME" in line:
                fixmes.append(f"{file}:{i}: {line.strip()}")

    if todos:
        print(f"📝 Found {len(todos)} TODO comments:")
        for todo in todos[:5]:
            print(f"   {todo}")
        if len(todos) > 5:
            print(f"   ... and {len(todos) - 5} more")
    else:
        print("✅ No TODO comments found")

    print()

    if fixmes:
        print(f"⚠️  Found {len(fixmes)} FIXME comments:")
        for fixme in fixmes:
            print(f"   {fixme}")
    else:
        print("✅ No FIXME comments found")

    print()


def check_import_patterns():
    """Check for inconsistent import patterns."""
    print("=" * 60)
    print("IMPORT PATTERN CHECK")
    print("=" * 60)

    issues = []

    # Check for "from __future__ import annotations" (shouldn't exist in 3.14)
    for file in Path("src/cemaf").rglob("*.py"):
        content = file.read_text()
        if "from __future__ import annotations" in content:
            issues.append(f"{file}: Still has 'from __future__ import annotations'")

    if issues:
        print(f"⚠️  Found {len(issues)} files with future annotations import:")
        for issue in issues:
            print(f"   {issue}")
    else:
        print("✅ No 'from __future__ import annotations' found")

    print()


def check_test_coverage():
    """Check test file structure."""
    print("=" * 60)
    print("TEST COVERAGE CHECK")
    print("=" * 60)

    modules_with_tests = set()

    for test_file in Path("tests/unit").rglob("test_*.py"):
        # Extract module name from test file
        module_name = test_file.stem.replace("test_", "")
        modules_with_tests.add(module_name)

    print(f"Found test files for {len(modules_with_tests)} modules")

    # Check which modules don't have tests
    modules_dir = Path("src/cemaf")
    all_modules = {d.name for d in modules_dir.iterdir() if d.is_dir() and not d.name.startswith("_")}

    missing_tests = all_modules - modules_with_tests
    if missing_tests:
        print(f"\n📋 Modules without dedicated test files ({len(missing_tests)}):")
        for m in sorted(missing_tests):
            print(f"   - {m}")

    print()


def main():
    """Run all checks."""
    print("\n" + "=" * 60)
    print("CEMAF COMPREHENSIVE AUDIT")
    print("=" * 60 + "\n")

    check_version_consistency()
    check_python_version_references()
    check_factory_completeness()
    check_settings_coverage()
    check_import_patterns()
    check_todos_and_fixmes()
    check_test_coverage()

    print("=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
