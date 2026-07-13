"""Crash-safety tests for local atomic replacement."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from cemaf.persistence.atomic_file import atomic_write_text


def test_interrupted_replace_preserves_last_good_file(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"version": 1}')
    original_replace = os.replace

    def interrupt_new_target(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == target:
            raise OSError("simulated process loss")
        original_replace(source, destination)

    with patch.object(os, "replace", interrupt_new_target), pytest.raises(OSError):
        atomic_write_text(target, '{"version": 2}')

    assert target.read_text(encoding="utf-8") == '{"version": 1}'
    assert target.with_suffix(".json.bak").read_text(encoding="utf-8") == '{"version": 1}'
