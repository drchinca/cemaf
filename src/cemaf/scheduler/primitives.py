"""Job classification + declarative definition for the scheduler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from cemaf.core.types import JSON
from cemaf.core.utils import safe_json
from cemaf.scheduler.protocols import Job, Trigger


class JobKind(StrEnum):
    """High-level job families for operator-facing classification."""

    STANDARD = "standard"
    DREAM = "dream"
    SYSTEM = "system"


@dataclass(frozen=True)
class JobDefinition:
    """Declarative description of a background job, materializable into a runtime ``Job``."""

    id: str
    name: str
    trigger: Trigger
    kind: JobKind = JobKind.STANDARD
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: float = 300.0
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: JSON = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def to_job(self, handler: Callable[[], Awaitable[Any]]) -> Job:
        """Materialize the runtime scheduler job object."""
        return Job(
            id=self.id,
            name=self.name,
            trigger=self.trigger,
            handler=handler,
            enabled=self.enabled,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            metadata=safe_json(dict(self.metadata)),
        )
