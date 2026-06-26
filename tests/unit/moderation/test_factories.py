"""Tests for moderation factory functions."""

from cemaf.events.bus import InMemoryEventBus
from cemaf.moderation.factories import (
    create_keyword_moderation_pipeline,
    create_keyword_rule,
    create_moderation_gate,
    create_moderation_pipeline,
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
