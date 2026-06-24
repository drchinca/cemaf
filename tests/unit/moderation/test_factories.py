"""Tests for moderation factory functions."""

from cemaf.events.bus import InMemoryEventBus
from cemaf.moderation.factories import (
    create_keyword_moderation_pipeline,
    create_keyword_rule,
    create_moderation_pipeline,
    create_post_flight_gate,
)
from cemaf.moderation.gates import PostFlightGate
from cemaf.moderation.rules import KeywordRule


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


def test_create_post_flight_gate_preserves_rules() -> None:
    rule = create_keyword_rule(blocked_words=("forbidden",))

    gate = create_post_flight_gate(rules=[rule], name="brand_post_flight")

    assert isinstance(gate, PostFlightGate)
    assert gate.name == "brand_post_flight"
    assert gate.rules == [rule]


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
