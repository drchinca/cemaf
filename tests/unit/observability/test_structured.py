"""Tests for StructuredLogger JSON-lines logger."""

import json
import logging
from io import StringIO
from unittest.mock import MagicMock

from cemaf.observability.protocols import Logger
from cemaf.observability.structured import StructuredLogger


class TestStructuredLoggerProtocol:
    def test_satisfies_logger_protocol(self) -> None:
        logger = StructuredLogger()
        assert isinstance(logger, Logger)


class TestStructuredLoggerOutput:
    def test_outputs_json_lines(self) -> None:
        buf = StringIO()
        logger = StructuredLogger(name="test", level=logging.DEBUG)
        logger._stream = buf

        logger.info("hello world")

        line = buf.getvalue().strip()
        record = json.loads(line)
        assert record["level"] == "INFO"
        assert record["message"] == "hello world"
        assert record["logger"] == "test"
        assert "timestamp" in record

    def test_with_context_merges(self) -> None:
        buf = StringIO()
        logger = StructuredLogger(name="test", level=logging.DEBUG)
        child = logger.with_context(request_id="abc-123")
        child._stream = buf

        child.info("processing", user="alice")

        record = json.loads(buf.getvalue().strip())
        assert record["request_id"] == "abc-123"
        assert record["user"] == "alice"
        assert record["message"] == "processing"

    def test_percent_formatting(self) -> None:
        buf = StringIO()
        logger = StructuredLogger(name="test", level=logging.DEBUG)
        logger._stream = buf

        logger.info("found %d items in %s", 42, "cache")

        record = json.loads(buf.getvalue().strip())
        assert record["message"] == "found 42 items in cache"

    def test_lazy_evaluation_skips_formatting(self) -> None:
        """Debug disabled at INFO level -- args never formatted."""
        buf = StringIO()
        logger = StructuredLogger(name="test", level=logging.INFO)
        logger._stream = buf

        expensive = MagicMock()
        expensive.__mod__ = MagicMock(return_value="formatted")

        logger.debug("value: %s", expensive)

        assert buf.getvalue() == ""

    def test_multiple_levels(self) -> None:
        buf = StringIO()
        logger = StructuredLogger(name="test", level=logging.DEBUG)
        logger._stream = buf

        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")

        lines = [json.loads(ln) for ln in buf.getvalue().strip().split("\n")]
        levels = [ln["level"] for ln in lines]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR"]

    def test_context_does_not_mutate_parent(self) -> None:
        parent = StructuredLogger(name="test")
        child = parent.with_context(extra="val")

        assert "extra" not in parent._context
        assert child._context["extra"] == "val"
