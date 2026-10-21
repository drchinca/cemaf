"""Report acceptance evidence without treating defects or missing cases as proof."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_CATALOG = pytest.StashKey[dict[str, dict[str, Any]]]()
_COLLECTED = pytest.StashKey[dict[str, set[str]]]()
_PASSED = pytest.StashKey[set[str]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-context-provenance",
        action="store_true",
        help="Require every context/provenance acceptance case to have passing executable evidence.",
    )
    parser.addoption(
        "--require-context-provenance-engineering",
        action="store_true",
        help="Require every automated acceptance case; live/human graduation remains separate.",
    )
    parser.addoption(
        "--context-provenance-map-out", help="Write collected case/test mappings for catalog maintenance"
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "context_acceptance(*case_ids): SPEC-17 policy-pilot acceptance cases")
    payload = json.loads(Path(__file__).with_name("cases.json").read_text())
    cases = payload["cases"]
    ids = [case["id"] for case in cases]
    if not cases or len(ids) != len(set(ids)):
        raise pytest.UsageError("Acceptance catalog must contain unique, nonempty cases")
    for case in cases:
        for field in ("id", "invariants", "given", "when", "then", "verification", "test_nodes"):
            if not case.get(field):
                raise pytest.UsageError(f"Acceptance case {case.get('id')} is missing {field}")
        if case["verification"] not in {"automated", "known_defect", "unimplemented", "pilot"}:
            raise pytest.UsageError(f"Unknown verification mode for {case['id']}")
        if case["verification"] != "automated" and not case.get("gap"):
            raise pytest.UsageError(f"Acceptance case {case['id']} must explain its evidence gap")
    config.stash[_CATALOG] = {case["id"]: case for case in cases}
    config.stash[_COLLECTED] = {case_id: set() for case_id in ids}
    config.stash[_PASSED] = set()


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    catalog = config.stash[_CATALOG]
    strict = config.getoption("--require-context-provenance", default=False) or config.getoption(
        "--require-context-provenance-engineering", default=False
    )
    for item in items:
        for marker in item.iter_markers("context_acceptance"):
            for case_id in marker.args:
                if case_id not in catalog:
                    raise pytest.UsageError(f"Unknown context acceptance case {case_id}")
                case = catalog[case_id]
                config.stash[_COLLECTED][case_id].add(item.nodeid)
                item.user_properties.append(("context_acceptance_case", case_id))
                item.user_properties.append(("context_acceptance_verification", case["verification"]))
                if case["verification"] == "known_defect" and not strict:
                    item.add_marker(pytest.mark.xfail(reason=case["gap"], strict=True, raises=AssertionError))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    passed = item.config.stash[_PASSED]
    if report.when == "call" and report.passed and not hasattr(report, "wasxfail"):
        passed.add(item.nodeid)
    if report.failed or report.skipped:
        passed.discard(item.nodeid)


def _verified(config: pytest.Config) -> set[str]:
    passed = config.stash[_PASSED]
    return {
        case_id
        for case_id, nodes in config.stash[_COLLECTED].items()
        if nodes and nodes <= passed and set(config.stash[_CATALOG][case_id]["test_nodes"]) <= passed
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    mapping_path = config.getoption("--context-provenance-map-out", default=None)
    if mapping_path:
        Path(mapping_path).write_text(
            json.dumps({key: sorted(nodes) for key, nodes in config.stash[_COLLECTED].items()}, indent=2)
            + "\n"
        )
    full = config.getoption("--require-context-provenance", default=False)
    engineering = config.getoption("--require-context-provenance-engineering", default=False)
    if not full and not engineering:
        return
    required = {
        case_id
        for case_id, case in config.stash[_CATALOG].items()
        if case["required"] and (full or case["verification"] != "pilot")
    }
    if required - _verified(config) and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus: int, config: pytest.Config) -> None:
    catalog = config.stash[_CATALOG]
    collected = config.stash[_COLLECTED]
    if (
        not any(collected.values())
        and not config.getoption("--require-context-provenance", default=False)
        and not config.getoption("--require-context-provenance-engineering", default=False)
    ):
        return
    verified = _verified(config)
    terminalreporter.section("Context and provenance acceptance")
    terminalreporter.write_line(
        f"Verified cases: {len(verified)}/{len(catalog)}; missing evidence is not a pass."
    )
    for case_id, case in catalog.items():
        if case_id in verified:
            continue
        state = "unresolved test" if collected[case_id] else "no executable evidence"
        terminalreporter.write_line(f"  {case_id}: {state} ({case['verification']})")


@pytest.fixture
def policy_corpus() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("policies.json").read_text())


@pytest.fixture(scope="session")
def policy_app():
    path = Path(__file__).resolve().parents[3] / "examples/app_shapes/policy_evidence.py"
    spec = importlib.util.spec_from_file_location("policy_evidence_acceptance_app", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
