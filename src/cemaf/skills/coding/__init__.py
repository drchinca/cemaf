"""Coding skill kit — the capabilities a code-writing agent calls in its loop.

All skills operate inside a single sandbox workspace (a ``ShellSandbox`` root):

- ``WriteFileSkill``  — create/overwrite a file (path-confined)
- ``ReadFileSkill``   — read a file (path-confined)
- ``EditFileSkill``   — exact-string replace in a file (path-confined)
- ``ListDirSkill``    — list the workspace tree
- ``ShellSkill``      — run any command in the sandbox
- ``RunTestsSkill``   — language-detecting test runner (pytest / vitest / go test / ...)

Domain-agnostic and language-agnostic: the kit is the substrate for a polyglot
spec→code loop (the agent writes Python, TypeScript, Go, Kotlin... and verifies
by running that ecosystem's test command).
"""

from cemaf.skills.coding.fileops import (
    EditFileInput,
    EditFileSkill,
    ListDirInput,
    ListDirSkill,
    ReadFileInput,
    ReadFileSkill,
    WriteFileInput,
    WriteFileSkill,
)
from cemaf.skills.coding.shell import ShellInput, ShellSkill
from cemaf.skills.coding.tests import RunTestsInput, RunTestsSkill, detect_test_command

__all__ = [
    "EditFileInput",
    "EditFileSkill",
    "ListDirInput",
    "ListDirSkill",
    "ReadFileInput",
    "ReadFileSkill",
    "RunTestsInput",
    "RunTestsSkill",
    "ShellInput",
    "ShellSkill",
    "WriteFileInput",
    "WriteFileSkill",
    "detect_test_command",
]
