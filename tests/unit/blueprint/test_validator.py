"""Unit tests for the SPEC-03 schema validation and repair primitive.

Real pydantic models and real validation errors throughout — no mocks.
"""

from __future__ import annotations

from pydantic import BaseModel

from cemaf.blueprint.validator import (
    ValidationOutcome,
    repair_and_validate,
    validate_structured_output,
)


class _OrderSummary(BaseModel):
    total: int
    currency: str


class TestValidateStructuredOutput:
    def test_conforming_output_is_valid(self) -> None:
        outcome = validate_structured_output(
            output_schema=_OrderSummary, raw_output={"total": 42, "currency": "USD"}
        )
        assert outcome.valid is True
        assert outcome.output == _OrderSummary(total=42, currency="USD")
        assert outcome.repair_hint is None
        assert outcome.attempts == 1

    def test_missing_and_wrong_type_fields_each_produce_one_note(self) -> None:
        outcome = validate_structured_output(output_schema=_OrderSummary, raw_output={"currency": 123})

        assert outcome.valid is False
        assert outcome.output is None
        assert outcome.repair_hint is not None
        assert len(outcome.repair_hint.notes) == 2
        field_paths = {note.field_path for note in outcome.repair_hint.notes}
        assert field_paths == {"total", "currency"}

    def test_repair_hint_carries_schema_name(self) -> None:
        outcome = validate_structured_output(output_schema=_OrderSummary, raw_output={})
        assert outcome.repair_hint is not None
        assert outcome.repair_hint.schema_name == "_OrderSummary"

    def test_every_note_has_non_default_guidance(self) -> None:
        outcome = validate_structured_output(output_schema=_OrderSummary, raw_output={})
        assert outcome.repair_hint is not None
        for note in outcome.repair_hint.notes:
            assert note.guidance
            assert note.error_type
            assert note.message


class TestSchemaRepairHintToPrompt:
    def test_renders_non_empty_text_naming_every_field(self) -> None:
        outcome = validate_structured_output(output_schema=_OrderSummary, raw_output={})
        assert outcome.repair_hint is not None

        prompt = outcome.repair_hint.to_prompt()

        assert prompt
        assert "total" in prompt
        assert "currency" in prompt

    def test_mentions_schema_name(self) -> None:
        outcome = validate_structured_output(output_schema=_OrderSummary, raw_output={})
        assert outcome.repair_hint is not None
        assert "_OrderSummary" in outcome.repair_hint.to_prompt()


class TestRepairAndValidate:
    async def test_converges_within_budget(self) -> None:
        calls: list[int] = []

        async def regenerate(hint: object) -> dict:
            calls.append(1)
            return {"total": 42, "currency": "USD"}

        outcome: ValidationOutcome[_OrderSummary] = await repair_and_validate(
            output_schema=_OrderSummary,
            raw_output={},
            max_attempts=3,
            regenerate=regenerate,
        )

        assert outcome.valid is True
        assert outcome.output == _OrderSummary(total=42, currency="USD")
        assert len(calls) == 1
        assert outcome.attempts == 2

    async def test_first_attempt_already_valid_never_calls_regenerate(self) -> None:
        async def regenerate(hint: object) -> dict:
            raise AssertionError("regenerate should not be called when the first attempt is valid")

        outcome = await repair_and_validate(
            output_schema=_OrderSummary,
            raw_output={"total": 1, "currency": "USD"},
            max_attempts=3,
            regenerate=regenerate,
        )

        assert outcome.valid is True
        assert outcome.attempts == 1

    async def test_exhausts_budget_without_converging(self) -> None:
        calls: list[int] = []

        async def regenerate(hint: object) -> dict:
            calls.append(1)
            return {}

        outcome = await repair_and_validate(
            output_schema=_OrderSummary,
            raw_output={},
            max_attempts=3,
            regenerate=regenerate,
        )

        assert outcome.valid is False
        assert outcome.output is None
        assert len(calls) == 2
        assert outcome.attempts == 3

    async def test_max_attempts_one_never_calls_regenerate(self) -> None:
        async def regenerate(hint: object) -> dict:
            raise AssertionError("regenerate should not be called when max_attempts == 1")

        outcome = await repair_and_validate(
            output_schema=_OrderSummary,
            raw_output={},
            max_attempts=1,
            regenerate=regenerate,
        )

        assert outcome.valid is False
        assert outcome.attempts == 1
