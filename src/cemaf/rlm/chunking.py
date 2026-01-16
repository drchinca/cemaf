"""
Chunking strategies for RLM.

Provides implementations for breaking large content into processable chunks
that respect token budgets and enable recursive querying.
"""

from cemaf.context.compiler import TokenEstimator
from cemaf.core.types import TokenCount
from cemaf.rlm.protocols import ContextChunk


class FixedSizeChunkingStrategy:
    """
    Simple fixed-size chunking strategy.

    Breaks content into chunks of approximately equal size based on
    token count estimation. Respects paragraph boundaries when possible.

    This is a simple baseline strategy. Future enhancements could include:
    - Semantic chunking (sentence/section aware)
    - Hierarchical chunking (parent summaries)
    - Sliding window (overlapping chunks)

    Example:
        estimator = SimpleTokenEstimator()
        strategy = FixedSizeChunkingStrategy(estimator, chunk_size=500)
        chunks = strategy.chunk(large_content, max_chunk_tokens=500)
    """

    def __init__(
        self,
        token_estimator: TokenEstimator,
        chunk_size: int = 500,
    ) -> None:
        """
        Initialize fixed-size chunking strategy.

        Args:
            token_estimator: Token estimator for chunk sizing
            chunk_size: Target tokens per chunk (default=500)
        """
        self._estimator = token_estimator
        self._chunk_size = chunk_size

    def chunk(
        self,
        content: str,
        max_chunk_tokens: int,
    ) -> tuple[ContextChunk, ...]:
        """
        Break content into fixed-size chunks.

        Splits on paragraph boundaries when possible to preserve semantic coherence.

        Args:
            content: Content to chunk
            max_chunk_tokens: Maximum tokens per chunk

        Returns:
            Tuple of context chunks
        """
        if not content.strip():
            return ()

        chunk_size = min(self._chunk_size, max_chunk_tokens)
        paragraphs = self._split_paragraphs(content)
        chunks: list[ContextChunk] = []
        current_chunk_paragraphs: list[str] = []
        current_tokens = 0

        for paragraph in paragraphs:
            para_tokens = self._estimator.estimate(paragraph)

            if para_tokens > chunk_size:
                if current_chunk_paragraphs:
                    chunks.append(
                        self._create_chunk(
                            chunk_id=f"chunk_{len(chunks)}",
                            content="\n\n".join(current_chunk_paragraphs),
                            token_count=TokenCount(current_tokens),
                            depth=0,
                        )
                    )
                    current_chunk_paragraphs = []
                    current_tokens = 0

                sentences = self._split_sentences(paragraph)
                sentence_chunks = self._chunk_sentences(
                    sentences,
                    chunk_size,
                    start_chunk_id=len(chunks),
                )
                chunks.extend(sentence_chunks)

            elif current_tokens + para_tokens > chunk_size:
                if current_chunk_paragraphs:
                    chunks.append(
                        self._create_chunk(
                            chunk_id=f"chunk_{len(chunks)}",
                            content="\n\n".join(current_chunk_paragraphs),
                            token_count=TokenCount(current_tokens),
                            depth=0,
                        )
                    )
                current_chunk_paragraphs = [paragraph]
                current_tokens = para_tokens

            else:
                current_chunk_paragraphs.append(paragraph)
                current_tokens += para_tokens

        if current_chunk_paragraphs:
            chunks.append(
                self._create_chunk(
                    chunk_id=f"chunk_{len(chunks)}",
                    content="\n\n".join(current_chunk_paragraphs),
                    token_count=TokenCount(current_tokens),
                    depth=0,
                )
            )

        return tuple(chunks)

    def create_hierarchy(
        self,
        chunks: tuple[ContextChunk, ...],
    ) -> tuple[ContextChunk, ...]:
        """
        Create hierarchical structure from flat chunks.

        For now, returns chunks as-is (flat structure).
        Future enhancement: Add parent summarization layer.

        Args:
            chunks: Flat list of chunks

        Returns:
            Tuple of chunks (currently unchanged)
        """
        return chunks

    def _split_paragraphs(self, content: str) -> list[str]:
        """Split content into paragraphs."""
        paragraphs = content.split("\n\n")
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences (simple implementation)."""
        import re

        sentence_endings = re.compile(r"([.!?]+[\s\n]+)")
        parts = sentence_endings.split(text)

        sentences: list[str] = []
        for i in range(0, len(parts) - 1, 2):
            sentence = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
            sentences.append(sentence.strip())

        if len(parts) % 2 == 1 and parts[-1].strip():
            sentences.append(parts[-1].strip())

        return [s for s in sentences if s]

    def _chunk_sentences(
        self,
        sentences: list[str],
        chunk_size: int,
        start_chunk_id: int,
    ) -> list[ContextChunk]:
        """Chunk sentences into fixed-size chunks."""
        chunks: list[ContextChunk] = []
        current_sentences: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = self._estimator.estimate(sentence)

            if sentence_tokens > chunk_size:
                if current_sentences:
                    chunks.append(
                        self._create_chunk(
                            chunk_id=f"chunk_{start_chunk_id + len(chunks)}",
                            content=" ".join(current_sentences),
                            token_count=TokenCount(current_tokens),
                            depth=0,
                        )
                    )
                    current_sentences = []
                    current_tokens = 0

                words = sentence.split()
                word_chunks = self._chunk_words(
                    words,
                    chunk_size,
                    start_chunk_id + len(chunks),
                )
                chunks.extend(word_chunks)

            elif current_tokens + sentence_tokens > chunk_size:
                if current_sentences:
                    chunks.append(
                        self._create_chunk(
                            chunk_id=f"chunk_{start_chunk_id + len(chunks)}",
                            content=" ".join(current_sentences),
                            token_count=TokenCount(current_tokens),
                            depth=0,
                        )
                    )
                current_sentences = [sentence]
                current_tokens = sentence_tokens

            else:
                current_sentences.append(sentence)
                current_tokens += sentence_tokens

        if current_sentences:
            chunks.append(
                self._create_chunk(
                    chunk_id=f"chunk_{start_chunk_id + len(chunks)}",
                    content=" ".join(current_sentences),
                    token_count=TokenCount(current_tokens),
                    depth=0,
                )
            )

        return chunks

    def _chunk_words(
        self,
        words: list[str],
        chunk_size: int,
        start_chunk_id: int,
    ) -> list[ContextChunk]:
        """Chunk words into fixed-size chunks."""
        chunks: list[ContextChunk] = []
        current_words: list[str] = []
        current_tokens = 0

        for word in words:
            word_tokens = self._estimator.estimate(word)

            if current_tokens + word_tokens > chunk_size:
                if current_words:
                    chunks.append(
                        self._create_chunk(
                            chunk_id=f"chunk_{start_chunk_id + len(chunks)}",
                            content=" ".join(current_words),
                            token_count=TokenCount(current_tokens),
                            depth=0,
                        )
                    )
                current_words = [word]
                current_tokens = word_tokens
            else:
                current_words.append(word)
                current_tokens += word_tokens

        if current_words:
            chunks.append(
                self._create_chunk(
                    chunk_id=f"chunk_{start_chunk_id + len(chunks)}",
                    content=" ".join(current_words),
                    token_count=TokenCount(current_tokens),
                    depth=0,
                )
            )

        return chunks

    def _create_chunk(
        self,
        chunk_id: str,
        content: str,
        token_count: TokenCount,
        depth: int,
        parent_id: str | None = None,
    ) -> ContextChunk:
        """Create a context chunk with generated ID."""
        return ContextChunk(
            chunk_id=chunk_id,
            content=content,
            token_count=token_count,
            parent_id=parent_id,
            depth=depth,
            metadata={"source": "fixed_size_chunking"},
        )
