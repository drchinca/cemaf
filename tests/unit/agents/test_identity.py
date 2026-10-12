"""Contract tests for AgentInstance and AgentDirectory shapes (SPEC-18 §2.1, L0)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from cemaf.agents.directory_protocols import AgentDirectory
from cemaf.agents.identity import AgentInstance, format_display_name
from cemaf.core.enums import InstanceStatus
from cemaf.core.types import AgentID, AttemptID, RunID, TaskID
from cemaf.core.utils import utc_now


def _instance(**overrides: object) -> AgentInstance:
    defaults: dict[str, object] = {
        "instance_id": uuid4(),
        "agent_id": AgentID("Researcher"),
        "display_name": "Researcher-1",
        "capabilities": frozenset({"search"}),
        "task_id": TaskID("task-1"),
        "run_id": RunID("run-1"),
        "status": InstanceStatus.QUEUED,
        "created_at": utc_now(),
        "attempt_id": AttemptID("attempt-1"),
    }
    defaults.update(overrides)
    return AgentInstance(**defaults)  # type: ignore[arg-type]


class TestAgentInstance:
    def test_frozen(self) -> None:
        instance = _instance()
        with pytest.raises(AttributeError):
            instance.status = InstanceStatus.RUNNING  # type: ignore[misc]

    def test_instance_id_is_a_real_uuid(self) -> None:
        # Every other ID in this codebase is a NewType(str) — instance_id is
        # deliberately a real uuid.UUID (SPEC-18 §2.1).
        instance = _instance()
        assert isinstance(instance.instance_id, UUID)

    def test_optional_fields_default_to_none(self) -> None:
        instance = _instance()
        assert instance.tenant_id is None
        assert instance.project_id is None
        assert instance.node_id is None
        assert instance.council_member_slot is None
        assert instance.parent_instance_id is None
        assert instance.terminal_at is None
        assert instance.replaces_id is None

    def test_to_dict_round_trip(self) -> None:
        parent_id = uuid4()
        instance = _instance(parent_instance_id=parent_id, capabilities=frozenset({"search", "cite"}))
        d = instance.to_dict()
        assert d["instance_id"] == str(instance.instance_id)
        assert d["agent_id"] == "Researcher"
        assert d["display_name"] == "Researcher-1"
        assert d["capabilities"] == ["cite", "search"]
        assert d["task_id"] == "task-1"
        assert d["run_id"] == "run-1"
        assert d["status"] == "queued"
        assert isinstance(d["created_at"], str)
        assert d["attempt_id"] == "attempt-1"
        assert d["parent_instance_id"] == str(parent_id)
        assert d["terminal_at"] is None
        assert d["replaces_id"] is None

    def test_to_dict_contains_all_fields(self) -> None:
        d = _instance().to_dict()
        expected_keys = {
            "instance_id",
            "agent_id",
            "display_name",
            "capabilities",
            "task_id",
            "run_id",
            "status",
            "created_at",
            "attempt_id",
            "tenant_id",
            "project_id",
            "node_id",
            "council_member_slot",
            "parent_instance_id",
            "terminal_at",
            "replaces_id",
        }
        assert set(d.keys()) == expected_keys


class TestFormatDisplayName:
    def test_formats_agent_id_and_ordinal(self) -> None:
        assert format_display_name(AgentID("Researcher"), 1) == "Researcher-1"
        assert format_display_name(AgentID("Researcher"), 2) == "Researcher-2"

    def test_distinct_ordinals_produce_distinct_names(self) -> None:
        names = {format_display_name(AgentID("Researcher"), ordinal) for ordinal in (1, 2, 3)}
        assert len(names) == 3


class TestAgentDirectoryProtocol:
    def test_conforming_object_satisfies_protocol(self) -> None:
        class _Directory:
            async def admit(self, **kwargs: object) -> AgentInstance: ...
            async def get(self, ref: object, **kwargs: object) -> AgentInstance | None: ...
            async def list(self, **kwargs: object) -> tuple[AgentInstance, ...]: ...
            async def transition(self, instance_id: object, **kwargs: object) -> AgentInstance: ...
            async def dispose(self, **kwargs: object) -> None: ...

        assert isinstance(_Directory(), AgentDirectory)

    def test_missing_method_fails_protocol(self) -> None:
        class _IncompleteDirectory:
            async def admit(self, **kwargs: object) -> AgentInstance: ...
            async def get(self, ref: object, **kwargs: object) -> AgentInstance | None: ...

            # no list/transition/dispose

        assert not isinstance(_IncompleteDirectory(), AgentDirectory)
