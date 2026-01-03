"""
Tests for LLM response utilities.
"""

from pydantic import BaseModel, Field

from cemaf.llm.response_utils import ParseResult, ResponseParser, StreamingJSONParser


class UserProfile(BaseModel):
    """Test model for validation."""

    name: str
    age: int
    email: str
    tags: list[str] = Field(default_factory=list)


class TestParseResult:
    """Tests for ParseResult."""

    def test_ok_result(self):
        """Create successful parse result."""
        result = ParseResult.ok(data={"key": "value"}, raw_content='{"key": "value"}')

        assert result.success is True
        assert result.data == {"key": "value"}
        assert result.error is None

    def test_fail_result(self):
        """Create failed parse result."""
        result = ParseResult.fail(
            error="Parse error",
            error_message="Failed to parse JSON",
            raw_content="invalid json",
        )

        assert result.success is False
        assert result.data is None
        assert result.error == "Parse error"
        assert result.error_message == "Failed to parse JSON"


class TestResponseParser:
    """Tests for ResponseParser."""

    def test_parse_plain_json(self):
        """Parse plain JSON string."""
        json_str = '{"name": "Alice", "age": 30}'
        result = ResponseParser.parse_json(json_str)

        assert result.success is True
        assert result.data == {"name": "Alice", "age": 30}

    def test_parse_json_code_block(self):
        """Parse JSON from markdown code block."""
        text = """
        Here's the result:
        ```json
        {
            "name": "Bob",
            "age": 25
        }
        ```
        """
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data == {"name": "Bob", "age": 25}

    def test_parse_json_code_block_no_language(self):
        """Parse JSON from code block without language specifier."""
        text = """
        ```
        {"name": "Charlie", "age": 35}
        ```
        """
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data == {"name": "Charlie", "age": 35}

    def test_parse_json_inline(self):
        """Parse JSON embedded in text."""
        text = 'The data is {"status": "ok", "count": 5} and that is all.'
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data == {"status": "ok", "count": 5}

    def test_parse_json_array(self):
        """Parse JSON array."""
        text = "[1, 2, 3, 4, 5]"
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data == [1, 2, 3, 4, 5]

    def test_parse_invalid_json(self):
        """Parse invalid JSON returns error."""
        text = '{"name": "Alice", age: 30}'  # Missing quotes around age
        result = ResponseParser.parse_json(text, strict=True)

        assert result.success is False
        assert "No valid JSON found" in (result.error or "")

    def test_parse_empty_text(self):
        """Parse empty text returns error."""
        result = ResponseParser.parse_json("", strict=True)

        assert result.success is False
        assert result.error == "Empty response"

    def test_parse_no_json_strict(self):
        """Parse text without JSON in strict mode."""
        text = "This is just plain text without any JSON."
        result = ResponseParser.parse_json(text, strict=True)

        assert result.success is False
        assert "No valid JSON found" in result.error or ""

    def test_parse_no_json_non_strict(self):
        """Parse text without JSON in non-strict mode."""
        text = "This is just plain text without any JSON."
        result = ResponseParser.parse_json(text, strict=False)

        assert result.success is True
        assert result.data is None

    def test_parse_to_model_success(self):
        """Parse and validate against Pydantic model."""
        text = """
        ```json
        {
            "name": "Alice",
            "age": 30,
            "email": "alice@example.com",
            "tags": ["python", "ai"]
        }
        ```
        """
        result = ResponseParser.parse_to_model(text, UserProfile)

        assert result.success is True
        assert isinstance(result.data, UserProfile)
        assert result.data.name == "Alice"
        assert result.data.age == 30
        assert result.data.email == "alice@example.com"
        assert result.data.tags == ["python", "ai"]

    def test_parse_to_model_missing_field(self):
        """Parse to model with missing required field."""
        text = """
        {
            "name": "Bob",
            "age": 25
        }
        """
        result = ResponseParser.parse_to_model(text, UserProfile, strict=True)

        assert result.success is False
        assert "Validation failed" in result.error or ""
        assert "email" in result.error_message or ""
        assert "Missing required field" in result.error_message or ""

    def test_parse_to_model_wrong_type(self):
        """Parse to model with wrong type."""
        text = """
        {
            "name": "Charlie",
            "age": "thirty",
            "email": "charlie@example.com"
        }
        """
        result = ResponseParser.parse_to_model(text, UserProfile, strict=True)

        assert result.success is False
        assert "Validation failed" in result.error or ""
        assert "age" in result.error_message or ""

    def test_parse_to_model_with_defaults(self):
        """Parse to model using default values."""
        text = """
        {
            "name": "David",
            "age": 40,
            "email": "david@example.com"
        }
        """
        result = ResponseParser.parse_to_model(text, UserProfile)

        assert result.success is True
        assert result.data.tags == []  # Default value

    def test_extract_or_default_success(self):
        """Extract value or return default."""
        text = '{"value": 42}'
        result = ResponseParser.extract_or_default(text, default=0)

        assert result == {"value": 42}

    def test_extract_or_default_failure(self):
        """Extract value returns default on failure."""
        text = "not valid json"
        result = ResponseParser.extract_or_default(text, default={"error": "default"})

        assert result == {"error": "default"}

    def test_extract_or_default_with_custom_extractor(self):
        """Extract with custom extractor function."""

        def extract_number(text: str) -> int:
            return int(text.split(":")[1].strip())

        text = "The answer is: 42"
        result = ResponseParser.extract_or_default(text, default=0, extractor=extract_number)

        assert result == 42

    def test_extract_or_default_custom_extractor_failure(self):
        """Custom extractor returns default on failure."""

        def extract_number(text: str) -> int:
            return int(text.split(":")[1].strip())

        text = "No number here"
        result = ResponseParser.extract_or_default(text, default=999, extractor=extract_number)

        assert result == 999


class TestStreamingJSONParser:
    """Tests for StreamingJSONParser."""

    def test_incremental_object_parsing(self):
        """Parse JSON object incrementally."""
        parser = StreamingJSONParser()

        chunks = [
            '{"name"',
            ': "Alice"',
            ', "age": ',
            "30}",
        ]

        for chunk in chunks[:-1]:
            parser.update(chunk)
            assert not parser.is_complete

        parser.update(chunks[-1])
        result = parser.get_result()

        assert result.success is True
        assert result.data == {"name": "Alice", "age": 30}

    def test_incremental_array_parsing(self):
        """Parse JSON array incrementally."""
        parser = StreamingJSONParser()

        chunks = ["[1, ", "2, ", "3, ", "4, ", "5]"]

        for chunk in chunks[:-1]:
            parser.update(chunk)
            assert not parser.is_complete

        parser.update(chunks[-1])
        result = parser.get_result()

        assert result.success is True
        assert result.data == [1, 2, 3, 4, 5]

    def test_code_block_streaming(self):
        """Parse JSON from streaming code block."""
        parser = StreamingJSONParser()

        chunks = [
            "```json\n",
            '{"status"',
            ': "ok"',
            "}\n",
            "```",
        ]

        for chunk in chunks:
            parser.update(chunk)

        result = parser.get_result()

        assert result.success is True
        assert result.data == {"status": "ok"}

    def test_accumulated_content(self):
        """Access accumulated content."""
        parser = StreamingJSONParser()

        chunks = ['{"a"', ": 1}"]
        for chunk in chunks:
            parser.update(chunk)

        assert parser.accumulated_content == '{"a": 1}'

    def test_reset(self):
        """Reset parser state."""
        parser = StreamingJSONParser()

        parser.update('{"test": 1}')
        parser.reset()

        assert parser.accumulated_content == ""
        assert not parser.is_complete

    def test_incomplete_json(self):
        """Get result with incomplete JSON."""
        parser = StreamingJSONParser()

        parser.update('{"incomplete":')
        result = parser.get_result()

        assert result.success is False

    def test_looks_like_complete_json_object(self):
        """Heuristic detects complete JSON object."""
        parser = StreamingJSONParser()

        parser.update('{"key": "value"}')
        # Should detect as complete based on balanced braces
        assert parser.accumulated_content == '{"key": "value"}'

    def test_looks_like_complete_json_array(self):
        """Heuristic detects complete JSON array."""
        parser = StreamingJSONParser()

        parser.update("[1, 2, 3]")
        # Should detect as complete based on balanced brackets
        assert parser.accumulated_content == "[1, 2, 3]"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_parse_nested_json(self):
        """Parse deeply nested JSON."""
        text = """
        {
            "level1": {
                "level2": {
                    "level3": {
                        "value": 42
                    }
                }
            }
        }
        """
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data["level1"]["level2"]["level3"]["value"] == 42

    def test_parse_json_with_unicode(self):
        """Parse JSON with unicode characters."""
        text = '{"message": "Hello 世界 🌍"}'
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data["message"] == "Hello 世界 🌍"

    def test_parse_json_with_escaped_quotes(self):
        """Parse JSON with escaped quotes."""
        text = r'{"quote": "He said \"Hello\""}'
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data["quote"] == 'He said "Hello"'

    def test_multiple_code_blocks(self):
        """Parse first JSON code block when multiple exist."""
        text = """First block:
```json
{"first": 1}
```

Second block:
```json
{"second": 2}
```
"""
        result = ResponseParser.parse_json(text)

        assert result.success is True
        assert result.data == {"first": 1}

    def test_parse_result_metadata(self):
        """ParseResult can store metadata."""
        result = ParseResult.fail(
            error="Test error",
            metadata={"validation_errors": [{"field": "name"}]},
        )

        assert result.metadata["validation_errors"] == [{"field": "name"}]
