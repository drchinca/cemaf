"""Check that the v3 release evidence page covers the public release contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/release_v3_evidence.md"
EXPECTED_VERSION = "3.0.0"

REQUIRED_REQUIREMENTS = tuple(f"REQ-{idx:02d}" for idx in range(1, 16))

REQUIRED_TEXT = (
    EXPECTED_VERSION,
    "drchinca/CMF-00/freemium_defaults",
    "local/free-first",
    "4067 passed",
    "328 unique",
    "550 total",
    "check_doc_voice.py",
    "check_release_naming.py",
    "check_loop_ops.py",
    "check_release_package.py",
    "uv build --out-dir /tmp/cemaf-v3-build-check",
    "Fresh wheel install smoke",
    "No matches",
    "Publication Boundary",
)


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def main() -> int:
    failures: list[str] = []

    if not EVIDENCE.is_file():
        failures.append("missing docs/release_v3_evidence.md")
        text = ""
    else:
        text = EVIDENCE.read_text(encoding="utf-8")

    for requirement_id in REQUIRED_REQUIREMENTS:
        if requirement_id not in text:
            failures.append(f"release evidence missing {requirement_id}")

    for needle in REQUIRED_TEXT:
        if needle not in text:
            failures.append(f"release evidence missing {needle!r}")

    docs_index = _read("docs/README.md")
    if "release_v3_evidence.md" not in docs_index:
        failures.append("docs/README.md must link to release_v3_evidence.md")

    readiness = _read("docs/release_v3_readiness.md")
    if "release_v3_evidence.md" not in readiness:
        failures.append("docs/release_v3_readiness.md must link to release_v3_evidence.md")
    if "check_release_evidence.py" not in readiness:
        failures.append("docs/release_v3_readiness.md must list check_release_evidence.py")

    makefile = _read("Makefile")
    if "check_release_evidence.py" not in makefile:
        failures.append("Makefile must wire check_release_evidence.py into audits")

    ci = _read(".github/workflows/ci.yml")
    if "check_release_evidence.py" not in ci:
        failures.append("CI docs audit must run check_release_evidence.py")

    if failures:
        print("Release evidence check failed:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(f"Release evidence check passed for {EXPECTED_VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
