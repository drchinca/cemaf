"""
Context adapters for various data types.

Implements ContextAdapter protocol for common data formats.
"""

from dataclasses import dataclass, field
from typing import Any

from cemaf.context.budget import TokenBudget
from cemaf.context.source import ContextSource
from cemaf.core.types import JSON


@dataclass
class TextAdapter:
    """
    Adapter for plain text content.

    Truncates or compresses text to fit within token budget.
    """

    max_tokens: int = 2000
    truncation_strategy: str = "tail"  # head, tail, middle
    preserve_structure: bool = True
    chars_per_token: float = 4.0

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if self.chars_per_token <= 0:
            raise ValueError(f"chars_per_token must be > 0, got {self.chars_per_token}")
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be > 0, got {self.max_tokens}")
        if self.truncation_strategy not in ("head", "tail", "middle"):
            raise ValueError(
                f"truncation_strategy must be 'head', 'tail', or 'middle', got '{self.truncation_strategy}'"
            )

    async def adapt(
        self,
        data: str,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """Adapt text to context source."""
        content = str(data)
        available = min(self.max_tokens, budget.available_tokens)

        # Truncate if needed
        estimated = self.estimate_tokens(content)
        if estimated > available:
            content = self._truncate(content, available)

        return ContextSource(
            type="text",
            key=f"text_{hash(data) % 10000}",
            content=content,
            token_count=self.estimate_tokens(content),
            priority=priority,
            metadata={"original_tokens": estimated},
        )

    def estimate_tokens(self, data: Any) -> int:
        """Estimate token count for text."""
        if not isinstance(data, str):
            data = str(data)
        return max(1, int(len(data) / self.chars_per_token))

    def _truncate(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit token limit."""
        max_chars = int(max_tokens * self.chars_per_token)

        if self.truncation_strategy == "head":
            return text[:max_chars] + "..." if len(text) > max_chars else text
        elif self.truncation_strategy == "tail":
            return "..." + text[-max_chars:] if len(text) > max_chars else text
        else:  # middle
            if len(text) <= max_chars:
                return text
            half = max_chars // 2
            return text[:half] + "\n...[truncated]...\n" + text[-half:]


@dataclass
class JSONAdapter:
    """
    Adapter for structured JSON data.

    Extracts relevant fields and flattens nested structures.
    """

    extract_fields: list[str] | None = None
    flatten_depth: int = 2
    array_limit: int = 10
    chars_per_token: float = 4.0

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if self.chars_per_token <= 0:
            raise ValueError(f"chars_per_token must be > 0, got {self.chars_per_token}")
        if self.flatten_depth < 0:
            raise ValueError(f"flatten_depth must be >= 0, got {self.flatten_depth}")
        if self.array_limit < 0:
            raise ValueError(f"array_limit must be >= 0, got {self.array_limit}")

    async def adapt(
        self,
        data: JSON,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """Adapt JSON data to context source."""
        # Extract specified fields or use all
        if self.extract_fields:
            extracted = {k: data.get(k) for k in self.extract_fields if k in data}
        else:
            extracted = data

        # Flatten and limit
        processed = self._process(extracted, depth=0)

        # Convert to string
        import json

        content = json.dumps(processed, indent=2, default=str)

        # Truncate if over budget
        available = budget.available_tokens
        if self.estimate_tokens(content) > available:
            content = content[: int(available * self.chars_per_token)]

        return ContextSource(
            type="json",
            key=f"json_{hash(str(data)) % 10000}",
            content=content,
            token_count=self.estimate_tokens(content),
            priority=priority,
            metadata={"fields": list(processed.keys()) if isinstance(processed, dict) else []},
        )

    def estimate_tokens(self, data: Any) -> int:
        """Estimate token count for JSON data."""
        import json

        if isinstance(data, str):
            return max(1, int(len(data) / self.chars_per_token))
        return max(1, int(len(json.dumps(data, default=str)) / self.chars_per_token))

    def _process(self, data: Any, depth: int) -> Any:
        """Process data with flattening and limits."""
        if depth > self.flatten_depth:
            return str(data) if data else None

        if isinstance(data, dict):
            return {k: self._process(v, depth + 1) for k, v in data.items()}
        elif isinstance(data, list):
            limited = data[: self.array_limit]
            return [self._process(item, depth + 1) for item in limited]
        else:
            return data


@dataclass
class TableAdapter:
    """
    Adapter for tabular data (DataFrames, CSV, SQL results).

    Formats as markdown or CSV for efficient token usage.
    """

    max_rows: int = 50
    priority_columns: list[str] | None = None
    format: str = "markdown"  # markdown, csv, json
    chars_per_token: float = 4.0

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if self.chars_per_token <= 0:
            raise ValueError(f"chars_per_token must be > 0, got {self.chars_per_token}")
        if self.max_rows < 0:
            raise ValueError(f"max_rows must be >= 0, got {self.max_rows}")
        if self.format not in ("markdown", "csv", "json"):
            raise ValueError(f"format must be 'markdown', 'csv', or 'json', got '{self.format}'")

    async def adapt(
        self,
        data: Any,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """Adapt tabular data to context source."""
        # Handle different input types
        rows, columns = self._extract_table(data)

        # Filter columns
        if self.priority_columns:
            columns = [c for c in self.priority_columns if c in columns]
            rows = [[row[i] for i, c in enumerate(columns)] for row in rows]

        # Limit rows
        rows = rows[: self.max_rows]

        # Format
        content = self._format_table(rows, columns)

        # Truncate if needed
        available = budget.available_tokens
        if self.estimate_tokens(content) > available:
            # Reduce rows until it fits
            while rows and self.estimate_tokens(content) > available:
                rows = rows[:-1]
                content = self._format_table(rows, columns)

        return ContextSource(
            type="table",
            key=f"table_{hash(str(data)[:100]) % 10000}",
            content=content,
            token_count=self.estimate_tokens(content),
            priority=priority,
            metadata={"rows": len(rows), "columns": columns},
        )

    def estimate_tokens(self, data: Any) -> int:
        """Estimate token count for table."""
        if isinstance(data, str):
            return max(1, int(len(data) / self.chars_per_token))
        return max(1, int(len(str(data)) / self.chars_per_token))

    def _extract_table(self, data: Any) -> tuple[list[list], list[str]]:
        """Extract rows and columns from various formats."""
        # Handle pandas DataFrame
        if hasattr(data, "to_dict") and hasattr(data, "columns"):
            columns = list(data.columns)
            rows = data.values.tolist()
            return rows, columns

        # Handle list of dicts
        if isinstance(data, list) and data and isinstance(data[0], dict):
            columns = list(data[0].keys())
            rows = [[row.get(c) for c in columns] for row in data]
            return rows, columns

        # Handle list of lists with header
        if isinstance(data, list) and len(data) > 1:
            columns = [str(c) for c in data[0]]
            rows = data[1:]
            return rows, columns

        return [], []

    def _format_table(self, rows: list[list], columns: list[str]) -> str:
        """Format table as string."""
        if not rows or not columns:
            return ""

        if self.format == "markdown":
            lines = []
            lines.append("| " + " | ".join(str(c) for c in columns) + " |")
            lines.append("| " + " | ".join("---" for _ in columns) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(v) for v in row) + " |")
            return "\n".join(lines)

        elif self.format == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            writer.writerows(rows)
            return output.getvalue()

        else:  # json
            import json

            return json.dumps([dict(zip(columns, row, strict=True)) for row in rows], indent=2)


@dataclass
class ChunkAdapter:
    """
    Adapter for documents that need splitting into chunks.

    Produces multiple context sources from a single document.
    """

    chunk_size: int = 500
    overlap: int = 50
    strategy: str = "fixed"  # fixed, sentence, semantic
    chars_per_token: float = 4.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate adapter configuration."""
        if self.chars_per_token <= 0:
            raise ValueError(f"chars_per_token must be > 0, got {self.chars_per_token}")
        if self.chunk_size <= 0:
            raise ValueError(f"chunk_size must be > 0, got {self.chunk_size}")
        if self.overlap < 0:
            raise ValueError(f"overlap must be >= 0, got {self.overlap}")
        # Auto-cap overlap to be less than chunk_size for usability
        if self.overlap >= self.chunk_size:
            object.__setattr__(self, "overlap", max(0, self.chunk_size - 1))
        if self.strategy not in ("fixed", "sentence", "semantic"):
            raise ValueError(f"strategy must be 'fixed', 'sentence', or 'semantic', got '{self.strategy}'")

    async def adapt(
        self,
        data: str,
        budget: TokenBudget,
        priority: int = 0,
    ) -> ContextSource:
        """Adapt to single source (first chunk only)."""
        chunks = await self.adapt_many(data, budget, base_priority=priority)
        return (
            chunks[0]
            if chunks
            else ContextSource(
                type="chunk",
                key="empty_chunk",
                content="",
                token_count=0,
                priority=priority,
            )
        )

    async def adapt_many(
        self,
        data: str,
        budget: TokenBudget,
        base_priority: int = 0,
    ) -> list[ContextSource]:
        """Adapt to multiple chunk sources."""
        text = str(data)
        chunks = self._split(text)

        sources = []
        for i, chunk in enumerate(chunks):
            estimated = self.estimate_tokens(chunk)
            if estimated > budget.available_tokens:
                chunk = chunk[: int(budget.available_tokens * self.chars_per_token)]

            sources.append(
                ContextSource(
                    type="chunk",
                    key=f"chunk_{i}",
                    content=chunk,
                    token_count=self.estimate_tokens(chunk),
                    priority=base_priority - i,  # Earlier chunks higher priority
                    metadata={
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        **self.metadata,
                    },
                )
            )

        return sources

    def estimate_tokens(self, data: Any) -> int:
        """Estimate token count."""
        if not isinstance(data, str):
            data = str(data)
        return max(1, int(len(data) / self.chars_per_token))

    def _split(self, text: str) -> list[str]:
        """Split text into chunks."""
        if self.strategy == "sentence":
            return self._split_sentences(text)
        else:  # fixed
            return self._split_fixed(text)

    def _split_fixed(self, text: str) -> list[str]:
        """Split into fixed-size chunks with overlap."""
        chunk_chars = int(self.chunk_size * self.chars_per_token)
        overlap_chars = int(self.overlap * self.chars_per_token)

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_chars
            chunks.append(text[start:end])
            start = end - overlap_chars

        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """Split into chunks at sentence boundaries."""
        import re

        sentences = re.split(r"(?<=[.!?])\s+", text)

        chunks = []
        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self.estimate_tokens(sentence)

            if current_tokens + sentence_tokens > self.chunk_size:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_tokens = sentence_tokens
            else:
                current_chunk.append(sentence)
                current_tokens += sentence_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
