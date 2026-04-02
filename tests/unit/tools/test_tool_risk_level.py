"""Tests for ToolRiskLevel enum and risk classification on tools."""

import pytest

from cemaf.core.enums import ToolRiskLevel
from cemaf.core.result import Result
from cemaf.core.types import ToolID
from cemaf.tools.base import Tool, ToolResult, ToolSchema, tool
from cemaf.tools.protocols import Tool as ToolProtocol

# ---------------------------------------------------------------------------
# ToolRiskLevel enum
# ---------------------------------------------------------------------------


class TestToolRiskLevel:
    def test_values(self) -> None:
        assert ToolRiskLevel.LOW == "low"
        assert ToolRiskLevel.MEDIUM == "medium"
        assert ToolRiskLevel.HIGH == "high"

    def test_three_levels(self) -> None:
        assert len(ToolRiskLevel) == 3


# ---------------------------------------------------------------------------
# ToolSchema risk_level
# ---------------------------------------------------------------------------


class TestToolSchemaRiskLevel:
    def test_default_is_medium(self) -> None:
        schema = ToolSchema(name="test", description="test")
        assert schema.risk_level == ToolRiskLevel.MEDIUM

    def test_explicit_low(self) -> None:
        schema = ToolSchema(
            name="reader",
            description="reads data",
            risk_level=ToolRiskLevel.LOW,
        )
        assert schema.risk_level == ToolRiskLevel.LOW

    def test_explicit_high(self) -> None:
        schema = ToolSchema(
            name="deployer",
            description="deploys code",
            risk_level=ToolRiskLevel.HIGH,
        )
        assert schema.risk_level == ToolRiskLevel.HIGH

    def test_frozen(self) -> None:
        schema = ToolSchema(name="test", description="test")
        with pytest.raises(AttributeError):
            schema.risk_level = ToolRiskLevel.HIGH  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tool ABC risk_level
# ---------------------------------------------------------------------------


class TestToolABCRiskLevel:
    def test_default_is_medium(self) -> None:
        class MinimalTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("minimal")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(name="minimal", description="minimal")

            async def execute(self, **kwargs: object) -> ToolResult:
                return Result.ok(data=None)

        assert MinimalTool().risk_level == ToolRiskLevel.MEDIUM

    def test_override_to_low(self) -> None:
        class SafeTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("safe")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(
                    name="safe",
                    description="safe",
                    risk_level=ToolRiskLevel.LOW,
                )

            @property
            def risk_level(self) -> ToolRiskLevel:
                return ToolRiskLevel.LOW

            async def execute(self, **kwargs: object) -> ToolResult:
                return Result.ok(data=None)

        assert SafeTool().risk_level == ToolRiskLevel.LOW

    def test_override_to_high(self) -> None:
        class DangerTool(Tool):
            @property
            def id(self) -> ToolID:
                return ToolID("danger")

            @property
            def schema(self) -> ToolSchema:
                return ToolSchema(
                    name="danger",
                    description="danger",
                    risk_level=ToolRiskLevel.HIGH,
                )

            @property
            def risk_level(self) -> ToolRiskLevel:
                return ToolRiskLevel.HIGH

            async def execute(self, **kwargs: object) -> ToolResult:
                return Result.ok(data=None)

        assert DangerTool().risk_level == ToolRiskLevel.HIGH


# ---------------------------------------------------------------------------
# @tool decorator risk_level
# ---------------------------------------------------------------------------


class TestToolDecoratorRiskLevel:
    def test_default_is_medium(self) -> None:
        @tool(name="simple", description="simple")
        async def simple() -> ToolResult:
            return Result.ok(data="ok")

        assert simple.risk_level == ToolRiskLevel.MEDIUM

    def test_decorator_protocol_compliance(self) -> None:
        @tool(name="proto", description="proto")
        async def proto() -> ToolResult:
            return Result.ok(data="ok")

        assert isinstance(proto, ToolProtocol)


# ---------------------------------------------------------------------------
# Risk level consistency with safety flags
# ---------------------------------------------------------------------------


class TestRiskLevelSafetyConsistency:
    """Risk level should be coherent with is_read_only / is_destructive."""

    def test_read_only_low_risk(self) -> None:
        schema = ToolSchema(
            name="reader",
            description="reads",
            is_read_only=True,
            risk_level=ToolRiskLevel.LOW,
        )
        assert schema.is_read_only is True
        assert schema.risk_level == ToolRiskLevel.LOW

    def test_destructive_high_risk(self) -> None:
        schema = ToolSchema(
            name="deleter",
            description="deletes",
            is_destructive=True,
            risk_level=ToolRiskLevel.HIGH,
        )
        assert schema.is_destructive is True
        assert schema.risk_level == ToolRiskLevel.HIGH
