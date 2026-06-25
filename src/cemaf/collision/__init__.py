"""Agent collision avoidance — TCAS-style coordination over ContextPatch paths (SPEC-12).

Detects when concurrent agents intend to write overlapping context paths and resolves the
conflict deterministically: the lower-priority agent steers away (defers) while the
higher-priority one holds course. Pure-math risk in ``risk``; advisory protocol in
``protocols``; the run-scoped coordinator in ``coordinator``.
"""

from cemaf.collision.coordinator import (
    CollisionCoordinator,
    TcasCollisionPolicy,
    emit_advisory,
)
from cemaf.collision.factories import (
    create_collision_coordinator,
    create_collision_policy,
)
from cemaf.collision.kg_distance import build_kg_dep_distance
from cemaf.collision.protocols import Advisory, CollisionPolicy
from cemaf.collision.risk import (
    DEFAULT_GAMMA,
    DEFAULT_WEIGHTS,
    TAU_RESOLUTION_ADVISORY,
    TAU_TRAFFIC_ADVISORY,
    AdvisoryLevel,
    AgentWriteSet,
    ChannelWeights,
    CollisionChannels,
    CollisionResult,
    WriteItem,
    collision_risk,
    has_right_of_way,
    overlap_coefficient,
    path_segments,
    tree_distance,
)

__all__ = [
    # risk (pure math)
    "AgentWriteSet",
    "WriteItem",
    "ChannelWeights",
    "CollisionChannels",
    "CollisionResult",
    "AdvisoryLevel",
    "collision_risk",
    "overlap_coefficient",
    "tree_distance",
    "path_segments",
    "has_right_of_way",
    "DEFAULT_WEIGHTS",
    "DEFAULT_GAMMA",
    "TAU_TRAFFIC_ADVISORY",
    "TAU_RESOLUTION_ADVISORY",
    # protocols
    "Advisory",
    "CollisionPolicy",
    # coordinator
    "CollisionCoordinator",
    "TcasCollisionPolicy",
    "emit_advisory",
    # factories
    "create_collision_coordinator",
    "create_collision_policy",
    # knowledge-graph dependency bridge
    "build_kg_dep_distance",
]
