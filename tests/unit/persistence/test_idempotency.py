"""Exactly-once behavior for the local idempotent effect destination."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cemaf.persistence.idempotency import FileIdempotentEffectSink, IdempotencyConflictError


@pytest.mark.asyncio
async def test_concurrent_duplicate_effect_is_created_once(tmp_path: Path) -> None:
    sink = FileIdempotentEffectSink(tmp_path)
    receipts = await asyncio.gather(
        *(sink.publish(key="run:publish", payload={"value": "done"}) for _ in range(20))
    )

    assert sum(receipt.created for receipt in receipts) == 1
    assert len(list(tmp_path.glob("*.effect.json"))) == 1


@pytest.mark.asyncio
async def test_idempotency_key_rejects_different_payload(tmp_path: Path) -> None:
    sink = FileIdempotentEffectSink(tmp_path)
    await sink.publish(key="run:publish", payload={"value": "first"})

    with pytest.raises(IdempotencyConflictError):
        await sink.publish(key="run:publish", payload={"value": "different"})
