"""Tests for moderation factory functions."""

import logging

import pytest

from cemaf.config.protocols import ModerationSettings, Settings
from cemaf.events.bus import InMemoryEventBus
from cemaf.events.protocols import Event
from cemaf.moderation.factories import (
    create_keyword_moderation_pipeline,
    create_keyword_rule,
    create_moderation_gate,
    create_moderation_pipeline,
    create_moderation_pipeline_from_config,
    create_moderation_rule,
    create_post_flight_gate,
    moderation_gate_registry,
    moderation_rule_registry,
)
from cemaf.moderation.gates import PostFlightGate
from cemaf.moderation.protocols import ModerationResult
from cemaf.moderation.rules import KeywordRule, PIIRule


class CustomRule:
    @property
    def name(self) -> str:
        return "custom_rule"

    async def check(self, content, context=None):  # noqa: ANN001, ANN201
        return ModerationResult.success()


class CustomGate:
    @property
    def name(self) -> str:
        return "custom_gate"

    async def check(self, content, context=None):  # noqa: ANN001, ANN201
        return ModerationResult.success()


class FailingEventBus:
    async def publish(self, event: Event) -> None:
        raise RuntimeError(f"bus down for {event.type}")

    async def publish_batch(self, events: list[Event]) -> None:
        for event in events:
            await self.publish(event)

    def subscribe(self, event_type, handler):  # noqa: ANN001, ANN201
        return lambda: None

    def subscribe_all(self, handler):  # noqa: ANN001, ANN201
        return lambda: None


def test_create_moderation_pipeline_preserves_custom_wiring() -> None:
    event_bus = InMemoryEventBus()
    post_flight = PostFlightGate(
        rules=[KeywordRule(blocked_words=("forbidden",), whole_word_only=False)],
        name="brand_post_flight",
    )

    pipeline = create_moderation_pipeline(
        post_flight=post_flight,
        event_bus=event_bus,
        name="brand_moderation",
    )

    assert pipeline.post_flight is post_flight
    assert pipeline.event_bus is event_bus
    assert pipeline.name == "brand_moderation"
    assert pipeline.enabled is True
    assert pipeline.fail_on_violation is True


@pytest.mark.asyncio
async def test_moderation_pipeline_disabled_bypasses_gate() -> None:
    post_flight = PostFlightGate(
        rules=[KeywordRule(blocked_words=("forbidden",), whole_word_only=False)],
        name="post",
    )
    pipeline = create_moderation_pipeline(enabled=False, post_flight=post_flight)

    result = await pipeline.check_output("forbidden")

    assert result.allowed is True
    assert result.metadata["reason"] == "disabled"


@pytest.mark.asyncio
async def test_moderation_pipeline_warn_mode_allows_violations() -> None:
    post_flight = PostFlightGate(
        rules=[KeywordRule(blocked_words=("forbidden",), whole_word_only=False)],
        name="post",
    )
    pipeline = create_moderation_pipeline(fail_on_violation=False, post_flight=post_flight)

    result = await pipeline.check_output("forbidden")

    assert result.allowed is True
    assert len(result.violations) == 1
    assert result.metadata["fail_on_violation"] is False
    assert result.metadata["original_allowed"] is False


def test_moderation_pipeline_from_config_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CEMAF_MODERATION_ENABLED", raising=False)
    monkeypatch.delenv("CEMAF_MODERATION_FAIL_ON_VIOLATION", raising=False)
    settings = Settings(
        moderation=ModerationSettings(
            enabled=False,
            fail_on_violation=False,
        )
    )

    pipeline = create_moderation_pipeline_from_config(settings=settings)

    assert pipeline.enabled is False
    assert pipeline.fail_on_violation is False


@pytest.mark.asyncio
async def test_moderation_pipeline_logs_event_publish_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = create_moderation_pipeline(event_bus=FailingEventBus())

    with caplog.at_level(logging.WARNING):
        result = await pipeline.check_input("safe content")
        await pipeline.flush_events()

    assert result.allowed is True
    assert "Failed to publish moderation event" in caplog.text
    assert "bus down for moderation.check.started" in caplog.text


def test_create_keyword_rule_preserves_blocked_words() -> None:
    rule = create_keyword_rule(blocked_words=("forbidden",), whole_word_only=False)

    assert isinstance(rule, KeywordRule)
    assert rule.blocked_words == ("forbidden",)
    assert rule.whole_word_only is False


def test_create_moderation_rule_uses_builtin_registry() -> None:
    rule = create_moderation_rule("pii", detect_phone=False)

    assert isinstance(rule, PIIRule)
    assert rule.detect_phone is False


def test_create_moderation_rule_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomRule()

    moderation_rule_registry.register(backend="custom-rule", factory=_factory)

    rule = create_moderation_rule("custom-rule", severity="warning")

    assert isinstance(rule, CustomRule)
    assert created["args"]["severity"] == "warning"


def test_create_post_flight_gate_preserves_rules() -> None:
    rule = create_keyword_rule(blocked_words=("forbidden",))

    gate = create_post_flight_gate(rules=[rule], name="brand_post_flight")

    assert isinstance(gate, PostFlightGate)
    assert gate.name == "brand_post_flight"
    assert gate.rules == [rule]


def test_create_moderation_gate_supports_custom_registered_backend() -> None:
    created: dict[str, object] = {}

    def _factory(**kwargs):
        created["args"] = kwargs
        return CustomGate()

    moderation_gate_registry.register(backend="custom-gate", factory=_factory)

    gate = create_moderation_gate("custom-gate", name="brand_gate")

    assert isinstance(gate, CustomGate)
    assert created["args"]["name"] == "brand_gate"


def test_create_keyword_moderation_pipeline_composes_keyword_gate() -> None:
    event_bus = InMemoryEventBus()

    pipeline = create_keyword_moderation_pipeline(
        blocked_words=("forbidden", "banned"),
        whole_word_only=False,
        event_bus=event_bus,
        gate_name="brand_post_flight",
        pipeline_name="brand_moderation",
    )

    assert pipeline.event_bus is event_bus
    assert pipeline.name == "brand_moderation"
    assert pipeline.post_flight is not None
    assert pipeline.post_flight.name == "brand_post_flight"
    assert len(pipeline.post_flight.rules) == 1
    rule = pipeline.post_flight.rules[0]
    assert isinstance(rule, KeywordRule)
    assert rule.blocked_words == ("forbidden", "banned")
    assert rule.whole_word_only is False
