"""
Factory functions for replay components.

Provides convenient ways to create replayer instances
with sensible defaults while maintaining dependency injection principles.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cemaf.core.types import JSON
from cemaf.observability.run_logger import RunRecord
from cemaf.replay.export import ReplayArtifactsBundle, export_replay_artifact
from cemaf.replay.replayer import Replayer, ReplayMode, ReplayResult


@dataclass(frozen=True)
class ReplayExecutionBundle:
    """Replay result plus exported artifact metadata for a persisted run record."""

    bundle_dir: Path
    artifact_path: Path
    result: ReplayResult
    artifact: ReplayArtifactsBundle


def _resolve_bundle_output_path(
    *,
    bundle_dir: Path,
    output_path: str | None,
    mode: ReplayMode,
) -> tuple[str, Path]:
    """Resolve an artifact path and keep replay exports confined to the bundle."""

    artifact_name = output_path or f"replay.{mode.value}.json"
    artifact_rel = Path(artifact_name)
    if artifact_rel.is_absolute():
        raise ValueError("Replay artifact output_path must be relative to the bundle directory.")

    artifact_path = (bundle_dir / artifact_rel).resolve()
    if not artifact_path.is_relative_to(bundle_dir):
        raise ValueError("Replay artifact output_path must stay within the bundle directory.")

    return artifact_rel.as_posix(), artifact_path


def create_replayer(
    record: RunRecord,
    mock_tools: dict[str, JSON] | None = None,
    tool_executors: dict[str, Callable[..., Any]] | None = None,
) -> Replayer:
    """
    Factory for Replayer with sensible defaults.

    Args:
        record: The RunRecord to replay
        mock_tools: Mock tool outputs for MOCK_TOOLS mode (optional)
        tool_executors: Real tool executors for LIVE_TOOLS mode (optional)

    Returns:
        Configured Replayer instance

    Example:
        # Basic replay (PATCH_ONLY mode)
        replayer = create_replayer(record=run_record)
        result = await replayer.replay()

        # With mocked tools
        mocks = {"web_search": {"results": [...]}}
        replayer = create_replayer(record=run_record, mock_tools=mocks)
        result = await replayer.replay(mode=ReplayMode.MOCK_TOOLS)

        # With real tool executors
        executors = {"calculator": my_calculator_fn}
        replayer = create_replayer(record=run_record, tool_executors=executors)
        result = await replayer.replay(mode=ReplayMode.LIVE_TOOLS)
    """
    return Replayer(
        record=record,
        mock_tools=mock_tools,
        tool_executors=tool_executors,
    )


async def replay_record_to_artifact(
    *,
    record_path: str | Path,
    mode: ReplayMode | str = ReplayMode.PATCH_ONLY,
    output_path: str | None = None,
    mock_tools: dict[str, JSON] | None = None,
    tool_executors: dict[str, Callable[..., Any]] | None = None,
) -> ReplayExecutionBundle:
    """Load a persisted run record, replay it, and export the replay artifact.

    ``output_path`` is written relative to the inspected bundle directory and may
    include nested subdirectories, but it must not be absolute or escape the
    bundle root.
    """

    from cemaf.observability.bundle import inspect_bundle_record_path

    inspection = inspect_bundle_record_path(record_path=record_path)
    record = inspection.run_record
    if record is None:
        raise ValueError(f"Replay record at {Path(record_path).resolve()} was not a loadable run record.")

    resolved_mode = mode if isinstance(mode, ReplayMode) else ReplayMode(mode)
    artifact_name, artifact_path = _resolve_bundle_output_path(
        bundle_dir=inspection.bundle_dir,
        output_path=output_path,
        mode=resolved_mode,
    )
    result = await create_replayer(
        record=record,
        mock_tools=mock_tools,
        tool_executors=tool_executors,
    ).replay(mode=resolved_mode)

    artifact = export_replay_artifact(
        root=inspection.bundle_dir,
        result=result,
        path=artifact_name,
    )
    return ReplayExecutionBundle(
        bundle_dir=inspection.bundle_dir,
        artifact_path=artifact_path,
        result=result,
        artifact=artifact,
    )
