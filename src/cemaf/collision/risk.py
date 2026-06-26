"""Agent collision risk — TCAS-style metric over ContextPatch write paths (SPEC-12).

Two agents writing overlapping context paths are like two aircraft sharing airspace:
we want a continuous notion of "how close are they" so that, as their intended write
sets converge, a coordinated advisory fires *before* they collide at merge time.

Collision is multi-channel. Each channel yields a probability r_i in [0,1]; they combine
with a noisy-OR (probability of colliding through at least one channel):

    R(a, b) = 1 - prod_i (1 - omega_i * r_i)

Channels:
  - overlap: same / nested write paths (Szymkiewicz-Simpson coefficient) — imminent.
  - dependency: one agent's path depends on the other's (injected graph distance) — far-apart hazard.
  - tree: proximity in the dot-path tree — a weak prior that nudges, never dominates.

Pure functions only: no I/O, no clock, no randomness — deterministic and unit-testable.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


@dataclass(frozen=True, slots=True)
class ChannelWeights:
    """Per-channel weights omega_i in the noisy-OR combination."""

    overlap: float = 1.0
    dependency: float = 0.9
    tree: float = 0.25


DEFAULT_WEIGHTS: Final[ChannelWeights] = ChannelWeights()
DEFAULT_GAMMA: Final[float] = 0.5  # dependency coupling decay per graph hop
RECENCY_FLOOR: Final[float] = 0.15  # write weights never decay below this


class AdvisoryLevel(StrEnum):
    """TCAS advisory bands carved by the two thresholds."""

    CLEAR = "clear"
    TRAFFIC_ADVISORY = "traffic_advisory"
    RESOLUTION_ADVISORY = "resolution_advisory"


TAU_TRAFFIC_ADVISORY: Final[float] = 0.35  # tau_TA
TAU_RESOLUTION_ADVISORY: Final[float] = 0.70  # tau_RA


@dataclass(frozen=True, slots=True)
class WriteItem:
    """One intended write: a dot-path and a recency weight in (0, 1]."""

    path: str
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class AgentWriteSet:
    """An agent's intended write set plus identity and start time for priority."""

    agent_id: str
    items: tuple[WriteItem, ...]
    started_at: float = 0.0  # caller-supplied epoch seconds; 0 ⇒ unknown


@dataclass(frozen=True, slots=True)
class CollisionChannels:
    """The three independent per-channel risks, each in [0, 1]."""

    overlap: float
    dependency: float
    tree: float


@dataclass(frozen=True, slots=True)
class CollisionResult:
    """Combined collision risk plus its dual distance and the channel breakdown."""

    risk: float
    distance: float
    channels: CollisionChannels


def clamp01(value: float) -> float:
    """Clamp a value into [0, 1]; non-finite collapses to 0."""
    if not math.isfinite(value):  # NaN / +inf / -inf guard
        return 0.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def path_segments(path: str) -> tuple[str, ...]:
    """Split a dot-path into non-empty segments — 'a.b.c' -> ('a','b','c')."""
    return tuple(segment for segment in path.split(".") if segment)


def tree_distance(a: str, b: str) -> float:
    """Normalized dot-path tree distance in [0, 1] — 0 = identical path, 1 = disjoint roots."""
    sa = path_segments(a)
    sb = path_segments(b)
    if not sa or not sb:
        return 1.0
    lca = 0
    while lca < len(sa) and lca < len(sb) and sa[lca] == sb[lca]:
        lca += 1
    da, db = len(sa), len(sb)
    if da == db and lca == da:
        return 0.0
    return clamp01((da - lca + (db - lca)) / (da + db))


def _is_path_overlap(a: str, b: str) -> bool:
    """True when two paths are identical or one is an ancestor of the other."""
    sa = path_segments(a)
    sb = path_segments(b)
    shorter, longer = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return longer[: len(shorter)] == shorter


def overlap_coefficient(a_paths: tuple[str, ...], b_paths: tuple[str, ...]) -> float:
    """Szymkiewicz-Simpson-style overlap over path-pairs (reference metric, exported for callers).

    Counts how many cross-pairs are in an ancestor/identical relation, normalized by the
    smaller set. High when one agent's path sits inside the other's subtree even if that
    subtree is large (union-based Jaccard would dilute it). Returns 0 for disjoint sets.

    Note: the internal overlap *channel* (``_overlap_channel``) is recency-weighted and uses
    a per-pair max; this set-level coefficient is the unweighted reference exposed for tests
    and external callers that want a plain overlap score.
    """
    if not a_paths or not b_paths:
        return 0.0
    matches = sum(1 for pa in a_paths for pb in b_paths if _is_path_overlap(pa, pb))
    return clamp01(matches / min(len(a_paths), len(b_paths)))


def _overlap_channel(a: AgentWriteSet, b: AgentWriteSet) -> float:
    """Recency-weighted max overlap across shared/nested paths (eq. 3)."""
    best = 0.0
    for ia in a.items:
        for ib in b.items:
            if _is_path_overlap(ia.path, ib.path):
                wa = max(ia.weight, RECENCY_FLOOR)
                wb = max(ib.weight, RECENCY_FLOOR)
                best = max(best, clamp01(wa * wb))
    return best


def _dependency_channel(
    a: AgentWriteSet,
    b: AgentWriteSet,
    dep_distance: Callable[[str, str], float] | None,
    gamma: float,
) -> float:
    """Recency-weighted max coupling gamma^(d-1) over cross path-pairs (eq. 5).

    ``dep_distance`` returns graph hops between two paths (a positive int-like float),
    or a non-finite / <1 value when unreachable. None ⇒ channel is 0 (no graph wired).
    """
    if dep_distance is None:
        return 0.0
    best = 0.0
    for ia in a.items:
        for ib in b.items:
            d = min(dep_distance(ia.path, ib.path), dep_distance(ib.path, ia.path))
            if not math.isfinite(d) or d < 1.0:  # unreachable / NaN / nonsensical hop
                continue
            coupling = gamma ** (d - 1.0)
            wa = max(ia.weight, RECENCY_FLOOR)
            wb = max(ib.weight, RECENCY_FLOOR)
            best = max(best, clamp01(wa * wb * coupling))
    return best


def _tree_channel(a: AgentWriteSet, b: AgentWriteSet) -> float:
    """Soft prior: 1 - min tree distance across cross path-pairs (eq. 6)."""
    if not a.items or not b.items:
        return 0.0
    min_dist = min(tree_distance(ia.path, ib.path) for ia in a.items for ib in b.items)
    return clamp01(1.0 - min_dist)


def collision_risk(
    a: AgentWriteSet,
    b: AgentWriteSet,
    *,
    dep_distance: Callable[[str, str], float] | None = None,
    weights: ChannelWeights = DEFAULT_WEIGHTS,
    gamma: float = DEFAULT_GAMMA,
) -> CollisionResult:
    """Combine the three channels via noisy-OR into a bounded collision risk."""
    if not 0.0 < gamma <= 1.0:
        raise ValueError(f"gamma must be in (0, 1]; got {gamma}")
    channels = CollisionChannels(
        overlap=_overlap_channel(a=a, b=b),
        dependency=_dependency_channel(a=a, b=b, dep_distance=dep_distance, gamma=gamma),
        tree=_tree_channel(a=a, b=b),
    )
    product = 1.0
    product *= 1.0 - clamp01(weights.overlap) * channels.overlap
    product *= 1.0 - clamp01(weights.dependency) * channels.dependency
    product *= 1.0 - clamp01(weights.tree) * channels.tree
    risk = clamp01(1.0 - product)
    return CollisionResult(risk=risk, distance=clamp01(1.0 - risk), channels=channels)


def _progress(write_set: AgentWriteSet) -> float:
    """Committed progress = sum of write weights (priority signal 1)."""
    return sum(max(item.weight, RECENCY_FLOOR) for item in write_set.items)


def has_right_of_way(a: AgentWriteSet, b: AgentWriteSet) -> bool:
    """Total deterministic priority: progress, then earlier start, then smaller agent_id.

    Returns True iff ``a`` holds right-of-way over ``b``. Total order ⇒ never a tie,
    provided the two agents have distinct ``agent_id`` (the final discriminator).
    """
    if a.agent_id == b.agent_id:
        raise ValueError(f"right-of-way requires distinct agent_ids; both are {a.agent_id!r}")
    pa, pb = _progress(a), _progress(b)
    if pa != pb:
        return pa > pb
    if a.started_at != b.started_at:
        # earlier start wins; started_at == 0 (unknown) sorts last so a known start beats it
        if a.started_at == 0.0:
            return False
        if b.started_at == 0.0:
            return True
        return a.started_at < b.started_at
    return a.agent_id < b.agent_id
