"""Tests for agent factory helpers."""

import pytest

from cemaf.agents.factories import create_agent_context_from_config
from cemaf.config.protocols import AgentsSettings, Settings
from cemaf.core.types import AgentID


def test_create_agent_context_from_config_uses_settings_depth_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CEMAF_AGENT_DEPTH", "2")
    settings = Settings(agents=AgentsSettings(deep_agent_max_depth=2))

    context = create_agent_context_from_config(
        AgentID("agent"),
        run_id="run-1",
        settings=settings,
    )

    assert context.depth == 2


def test_create_agent_context_from_config_rejects_depth_over_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CEMAF_AGENT_DEPTH", "3")
    settings = Settings(agents=AgentsSettings(deep_agent_max_depth=2))

    with pytest.raises(ValueError, match="exceeds configured"):
        create_agent_context_from_config(AgentID("agent"), settings=settings)


def test_create_agent_context_from_config_rejects_negative_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CEMAF_AGENT_DEPTH", "-1")

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        create_agent_context_from_config(AgentID("agent"))
