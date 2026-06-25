"""Factories for the collision package (SPEC-12)."""

from collections.abc import Callable

from cemaf.collision.coordinator import CollisionCoordinator, TcasCollisionPolicy
from cemaf.collision.risk import DEFAULT_GAMMA, DEFAULT_WEIGHTS, ChannelWeights


def create_collision_policy(
    *,
    dep_distance: Callable[[str, str], float] | None = None,
    weights: ChannelWeights = DEFAULT_WEIGHTS,
    gamma: float = DEFAULT_GAMMA,
) -> TcasCollisionPolicy:
    """Build the default TCAS collision policy."""
    return TcasCollisionPolicy(dep_distance=dep_distance, weights=weights, gamma=gamma)


def create_collision_coordinator(
    *,
    dep_distance: Callable[[str, str], float] | None = None,
    cohort_size: int | None = None,
) -> CollisionCoordinator:
    """Build a run-scoped collision coordinator with the default TCAS policy."""
    policy = create_collision_policy(dep_distance=dep_distance)
    return CollisionCoordinator(policy=policy, cohort_size=cohort_size)
