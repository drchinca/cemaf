"""
External notifier implementations.

Provides webhook, logging, and composite notifiers.
"""

import json
import logging
from collections.abc import Sequence
from typing import Any

from cemaf.events.protocols import Event, Notifier, NotifyResult

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """
    Send events to a webhook URL.

    Note: This is a protocol-compliant shell. For actual HTTP calls,
    inject an HTTP client or extend with your preferred library
    (httpx, aiohttp, etc.).
    """

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30.0,
        name: str | None = None,
        http_client: Any | None = None,  # Inject your HTTP client
    ) -> None:
        """
        Initialize webhook notifier.

        Args:
            url: Webhook URL to POST to.
            headers: Additional HTTP headers.
            timeout_seconds: Request timeout.
            name: Notifier name.
            http_client: Optional HTTP client (e.g., httpx.AsyncClient).
        """
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout_seconds
        self._name = name or f"webhook:{url}"
        self._http_client = http_client

    @property
    def name(self) -> str:
        return self._name

    async def notify(self, event: Event) -> NotifyResult:
        """
        Send event to webhook.

        If no HTTP client is configured, returns a placeholder result.
        """
        payload = {
            "id": event.id,
            "type": event.type,
            "timestamp": event.timestamp.isoformat(),
            "source": event.source,
            "payload": event.payload,
            "correlation_id": event.correlation_id,
            "metadata": event.metadata,
        }

        if self._http_client is None:
            # No HTTP client - log and return placeholder
            logger.info(
                "Webhook notify (no client): %s -> %s",
                event.type,
                self._url,
            )
            return NotifyResult.ok(f"Webhook prepared (no HTTP client): {self._url}")

        try:
            # If client is provided, attempt to use it
            # This assumes an httpx-like interface
            response = await self._http_client.post(
                self._url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    **self._headers,
                },
                timeout=self._timeout,
            )

            if response.status_code >= 400:
                return NotifyResult.fail(
                    f"Webhook returned {response.status_code}",
                    retry_after=60 if response.status_code >= 500 else None,
                )

            return NotifyResult.ok(f"Webhook delivered: {response.status_code}")

        except Exception as e:
            return NotifyResult.fail(str(e), retry_after=30)


class LoggingNotifier:
    """
    Log events using Python logging.

    Useful for development/debugging or as a fallback.
    """

    def __init__(
        self,
        logger_name: str = "cemaf.events",
        level: int = logging.INFO,
        name: str = "logging",
    ) -> None:
        """
        Initialize logging notifier.

        Args:
            logger_name: Logger name to use.
            level: Logging level.
            name: Notifier name.
        """
        self._logger = logging.getLogger(logger_name)
        self._level = level
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def notify(self, event: Event) -> NotifyResult:
        """Log the event."""
        self._logger.log(
            self._level,
            "Event [%s] from %s: %s",
            event.type,
            event.source or "unknown",
            json.dumps(event.payload),
        )
        return NotifyResult.ok("Logged")


class CompositeNotifier:
    """
    Send events to multiple notifiers.

    Aggregates results from all notifiers.
    """

    def __init__(
        self,
        notifiers: Sequence[Notifier],
        fail_fast: bool = False,
        name: str = "composite",
    ) -> None:
        """
        Initialize composite notifier.

        Args:
            notifiers: Notifiers to delegate to.
            fail_fast: Stop on first failure.
            name: Notifier name.
        """
        self._notifiers = list(notifiers)
        self._fail_fast = fail_fast
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def add_notifier(self, notifier: Notifier) -> None:
        """Add a notifier."""
        self._notifiers.append(notifier)

    async def notify(self, event: Event) -> NotifyResult:
        """
        Send to all notifiers.

        Returns success if all notifiers succeed, otherwise returns
        the first failure.
        """
        results: list[NotifyResult] = []
        errors: list[str] = []

        for notifier in self._notifiers:
            result = await notifier.notify(event)
            results.append(result)

            if not result.success:
                errors.append(f"{notifier.name}: {result.error}")
                if self._fail_fast:
                    return NotifyResult.fail(
                        f"Failed at {notifier.name}: {result.error}",
                        retry_after=result.retry_after,
                    )

        if errors:
            return NotifyResult(
                success=False,
                error=f"Partial failure: {'; '.join(errors)}",
                metadata={"errors": errors},
            )

        return NotifyResult.ok(f"Notified {len(self._notifiers)} targets")
