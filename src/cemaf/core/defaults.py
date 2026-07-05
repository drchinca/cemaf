"""Project-wide free/offline-first defaults.

These defaults keep a zero-config CEMAF process away from paid or hosted
providers. Explicit provider factories may still choose provider-native model
defaults after the caller opts into that backend.
"""

from typing import Final, Literal

DEFAULT_FREE_LLM_PROVIDER: Final[Literal["ollama"]] = "ollama"
DEFAULT_FREE_LLM_MODEL: Final = "gemma3:4b"
DEFAULT_FREE_EMBEDDING_PROVIDER: Final[Literal["hash"]] = "hash"
DEFAULT_FREE_EMBEDDING_MODEL: Final = "hash-embedding"
DEFAULT_FREE_EMBEDDING_DIMENSION: Final = 384
DEFAULT_FREE_CATALOG_BACKEND: Final[Literal["static"]] = "static"
