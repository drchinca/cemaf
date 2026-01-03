"""
LLM response utilities - Comprehensive parsing and validation for LLM outputs.

Provides utilities for:
- Extracting JSON from markdown code blocks
- Validating responses against Pydantic models
- Streaming JSON parsing
- Safe fallback extraction
- Error feedback for LLM retry loops

Common Usage:
    # Parse JSON from response
    result = ResponseParser.parse_json(llm_response)
    if result.success:
        data = result.data

    # Parse and validate with Pydantic model
    result = ResponseParser.parse_to_model(llm_response, UserProfile)
    if not result.success:
        # Error message includes suggestions for LLM to fix
        print(result.error_message)

    # Streaming parser for incremental JSON
    async for chunk in stream_chunks:
        parser.update(chunk.content)
        if parser.is_complete:
            data = parser.get_result()
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from cemaf.core.types import JSON

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


@dataclass(frozen=True)
class ParseResult[T]:
    """
    Result of parsing an LLM response.

    Provides both success/failure status and helpful error messages
    for retry loops.
    """

    success: bool
    data: T | None = None
    error: str | None = None
    error_message: str | None = None  # Human-readable error for LLM feedback
    raw_content: str = ""
    metadata: JSON = field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, raw_content: str = "", metadata: JSON | None = None) -> ParseResult[T]:
        """Create a successful parse result."""
        return cls(
            success=True,
            data=data,
            raw_content=raw_content,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        error: str,
        error_message: str | None = None,
        raw_content: str = "",
        metadata: JSON | None = None,
    ) -> ParseResult[T]:
        """Create a failed parse result."""
        return cls(
            success=False,
            error=error,
            error_message=error_message or error,
            raw_content=raw_content,
            metadata=metadata or {},
        )


class ResponseParser:
    """
    Utility class for parsing LLM responses.

    Handles common patterns like:
    - JSON in markdown code blocks
    - Plain JSON
    - Pydantic model validation
    - Error feedback generation
    """

    # Regex patterns for extracting JSON from various formats
    JSON_CODE_BLOCK_PATTERN = re.compile(
        r"```(?:json)?\s*\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )
    JSON_INLINE_PATTERN = re.compile(
        r"\{.*\}|\[.*\]",
        re.DOTALL,
    )

    @classmethod
    def parse_json(cls, text: str, *, strict: bool = True) -> ParseResult[JSON]:
        """
        Parse JSON from LLM response text.

        Tries multiple extraction strategies:
        1. Extract from markdown code blocks (```json ... ```)
        2. Extract first JSON-like structure
        3. Parse entire text as JSON

        Args:
            text: LLM response text
            strict: If True, require valid JSON. If False, return None on failure.

        Returns:
            ParseResult with parsed JSON or error
        """
        if not text or not text.strip():
            return ParseResult.fail(
                error="Empty response",
                error_message="The response was empty. Please provide a JSON response.",
                raw_content=text,
            )

        # Strategy 1: Try markdown code block
        match = cls.JSON_CODE_BLOCK_PATTERN.search(text)
        if match:
            json_str = match.group(1).strip()
            return cls._parse_json_string(json_str, raw_content=text)

        # Strategy 2: Extract first JSON-like structure
        match = cls.JSON_INLINE_PATTERN.search(text)
        if match:
            json_str = match.group(0).strip()
            result = cls._parse_json_string(json_str, raw_content=text)
            if result.success:
                return result

        # Strategy 3: Try parsing entire text as JSON
        result = cls._parse_json_string(text.strip(), raw_content=text)
        if result.success:
            return result

        # Failed all strategies
        if strict:
            return ParseResult.fail(
                error="No valid JSON found",
                error_message=(
                    "Could not find valid JSON in response. "
                    "Please wrap JSON in ```json code blocks or provide plain JSON."
                ),
                raw_content=text,
            )

        return ParseResult.ok(data=None, raw_content=text)

    @classmethod
    def _parse_json_string(cls, json_str: str, raw_content: str = "") -> ParseResult[JSON]:
        """Parse a JSON string and return result."""
        try:
            data = json.loads(json_str)
            return ParseResult.ok(data=data, raw_content=raw_content)
        except json.JSONDecodeError as e:
            return ParseResult.fail(
                error=f"Invalid JSON: {e}",
                error_message=(
                    f"JSON parsing failed at position {e.pos}: {e.msg}. "
                    "Please check for:\n"
                    "- Missing or extra commas\n"
                    "- Unquoted keys or string values\n"
                    "- Trailing commas\n"
                    "- Invalid escape sequences"
                ),
                raw_content=raw_content,
            )

    @classmethod
    def parse_to_model(
        cls,
        text: str,
        model_class: type[M],
        *,
        strict: bool = True,
    ) -> ParseResult[M]:
        """
        Parse JSON from text and validate against Pydantic model.

        Args:
            text: LLM response text
            model_class: Pydantic model class to validate against
            strict: If True, require valid JSON and model validation

        Returns:
            ParseResult with validated model instance or error with feedback
        """
        # First parse JSON
        json_result = cls.parse_json(text, strict=strict)
        if not json_result.success:
            return ParseResult.fail(
                error=json_result.error or "JSON parsing failed",
                error_message=json_result.error_message,
                raw_content=text,
            )

        if json_result.data is None:
            return ParseResult.fail(
                error="No JSON data",
                error_message="No JSON data found to validate",
                raw_content=text,
            )

        # Validate against model
        try:
            model_instance = model_class.model_validate(json_result.data)
            return ParseResult.ok(data=model_instance, raw_content=text)
        except ValidationError as e:
            # Generate helpful error message for LLM
            error_details = cls._format_validation_errors(e, model_class)
            return ParseResult.fail(
                error=f"Validation failed: {e}",
                error_message=error_details,
                raw_content=text,
                metadata={"validation_errors": e.errors()},
            )

    @classmethod
    def _format_validation_errors(cls, error: ValidationError, model_class: type[BaseModel]) -> str:
        """Format validation errors into helpful feedback for LLM."""
        errors = error.errors()
        error_lines = ["Validation failed against schema. Please fix the following:"]

        for err in errors:
            field = ".".join(str(loc) for loc in err["loc"])
            msg = err["msg"]
            error_type = err["type"]

            if error_type == "missing":
                error_lines.append(f"- Missing required field '{field}'")
            elif error_type in {"string_type", "int_parsing", "float_parsing", "bool_parsing"}:
                error_lines.append(f"- Field '{field}': {msg}")
            else:
                error_lines.append(f"- Field '{field}': {msg}")

        # Add schema hint
        error_lines.append(f"\nExpected schema for {model_class.__name__}:")
        error_lines.append(f"{model_class.model_json_schema()}")

        return "\n".join(error_lines)

    @classmethod
    def extract_or_default(
        cls,
        text: str,
        default: T,
        *,
        extractor: Callable[[str], T] | None = None,
    ) -> T:
        """
        Extract value from text or return default.

        Safe extraction with fallback for non-critical parsing.

        Args:
            text: Text to extract from
            default: Default value if extraction fails
            extractor: Custom extraction function. Defaults to JSON parsing.

        Returns:
            Extracted value or default
        """
        if extractor is None:
            result = cls.parse_json(text, strict=False)
            return result.data if result.success and result.data is not None else default

        try:
            return extractor(text)
        except Exception:
            return default


class StreamingJSONParser:
    """
    Parser for incremental JSON from streaming LLM responses.

    Accumulates chunks and attempts to parse when complete JSON is detected.

    Usage:
        parser = StreamingJSONParser()

        async for chunk in stream_chunks:
            parser.update(chunk.content)

            if parser.is_complete:
                data = parser.get_result()
                if data.success:
                    process(data.data)
    """

    def __init__(self) -> None:
        """Initialize streaming parser."""
        self._buffer: list[str] = []
        self._accumulated = ""
        self._result: ParseResult[JSON] | None = None

    def update(self, chunk: str) -> None:
        """
        Add a new chunk to the buffer.

        Args:
            chunk: New content from streaming response
        """
        self._buffer.append(chunk)
        self._accumulated += chunk

        # Try parsing accumulated content
        if self._looks_like_complete_json(self._accumulated):
            self._result = ResponseParser.parse_json(self._accumulated, strict=False)

    def _looks_like_complete_json(self, text: str) -> bool:
        """
        Heuristic check if text might contain complete JSON.

        Not guaranteed to be accurate, but reduces failed parse attempts.
        """
        text = text.strip()
        if not text:
            return False

        # Check for balanced braces/brackets
        if text.startswith("{") and text.endswith("}"):
            return text.count("{") == text.count("}")
        if text.startswith("[") and text.endswith("]"):
            return text.count("[") == text.count("]")

        # Check for code block completion
        if "```" in text:
            return text.count("```") % 2 == 0

        return False

    @property
    def is_complete(self) -> bool:
        """Check if valid JSON has been parsed."""
        return self._result is not None and self._result.success

    def get_result(self) -> ParseResult[JSON]:
        """
        Get parse result.

        Returns:
            ParseResult with parsed JSON or error
        """
        if self._result is not None:
            return self._result

        # Try one final parse with accumulated content
        return ResponseParser.parse_json(self._accumulated, strict=True)

    def reset(self) -> None:
        """Reset parser state for reuse."""
        self._buffer.clear()
        self._accumulated = ""
        self._result = None

    @property
    def accumulated_content(self) -> str:
        """Get all accumulated content."""
        return self._accumulated
