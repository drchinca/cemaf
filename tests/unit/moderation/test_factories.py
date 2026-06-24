"""Tests for moderation factory functions."""

from cemaf.events.bus import InMemoryEventBus
from cemaf.moderation.factories import create_moderation_pipeline
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
