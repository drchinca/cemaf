"""Tests for RuntimeServices dataclass."""

import pytest

from cemaf.orchestration.services import RuntimeServices


class TestRuntimeServices:
    def test_default_all_none(self):
        """All fields default to None."""
        svc = RuntimeServices()
        assert svc.run_logger is None
        assert svc.event_bus is None
        assert svc.memory_manager is None
        assert svc.session_manager is None
        assert svc.llm_client is None

    def test_frozen(self):
        """RuntimeServices is immutable."""
        svc = RuntimeServices()
        with pytest.raises(AttributeError):
            svc.run_logger = "something"  # type: ignore[misc]

    def test_selective_population(self):
        """Can populate only needed services."""
        from cemaf.observability.run_logger import InMemoryRunLogger

        logger = InMemoryRunLogger()
        svc = RuntimeServices(run_logger=logger)
        assert svc.run_logger is logger
        assert svc.event_bus is None

    def test_agent_directory_defaults_to_none(self):
        """RuntimeServices() with no agent_directory still succeeds unconditionally (invariant 10)."""
        svc = RuntimeServices()
        assert svc.agent_directory is None

    def test_agent_directory_accepts_conforming_implementation(self):
        from cemaf.agents.factories import create_agent_directory

        directory = create_agent_directory()
        svc = RuntimeServices(agent_directory=directory)
        assert svc.agent_directory is directory

    def test_agent_directory_rejects_non_conforming_object(self):
        with pytest.raises(ValueError, match="AgentDirectory protocol"):
            RuntimeServices(agent_directory=object())  # type: ignore[arg-type]
