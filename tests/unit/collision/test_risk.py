"""SPEC-12 — unit tests for collision risk math + advisory policy."""

import pytest

from cemaf.collision import (
    AdvisoryLevel,
    AgentWriteSet,
    CollisionPolicy,
    TcasCollisionPolicy,
    WriteItem,
    collision_risk,
    has_right_of_way,
    overlap_coefficient,
    tree_distance,
)
from cemaf.collision.risk import clamp01


def _ws(agent_id: str, *paths: str, weight: float = 1.0, started_at: float = 0.0) -> AgentWriteSet:
    return AgentWriteSet(
        agent_id=agent_id,
        items=tuple(WriteItem(path=p, weight=weight) for p in paths),
        started_at=started_at,
    )


class TestTreeDistance:
    def test_identical_path_is_zero(self) -> None:
        assert tree_distance("draft.body", "draft.body") == 0.0

    def test_disjoint_roots_is_one(self) -> None:
        assert tree_distance("research.findings", "draft.outline") == 1.0

    def test_shared_prefix_between_zero_and_one(self) -> None:
        d = tree_distance("draft.body", "draft.outline")
        assert 0.0 < d < 1.0

    def test_empty_path_is_max_distance(self) -> None:
        assert tree_distance("", "draft") == 1.0


class TestOverlapCoefficient:
    def test_identical_paths_full_overlap(self) -> None:
        assert overlap_coefficient(("draft.body",), ("draft.body",)) == 1.0

    def test_nested_path_overlaps(self) -> None:
        # "draft" is an ancestor of "draft.body.intro"
        assert overlap_coefficient(("draft",), ("draft.body.intro",)) == 1.0

    def test_disjoint_paths_zero(self) -> None:
        assert overlap_coefficient(("research.findings",), ("draft.outline",)) == 0.0

    def test_empty_zero(self) -> None:
        assert overlap_coefficient((), ("a",)) == 0.0


class TestCollisionRisk:
    def test_risk_is_bounded_and_dual(self) -> None:
        """Inv 1 — R in [0,1] and distance == 1 - R."""
        result = collision_risk(_ws("a", "draft.body"), _ws("b", "draft.body"))
        assert 0.0 <= result.risk <= 1.0
        assert result.distance == pytest.approx(1.0 - result.risk)

    def test_disjoint_sets_zero_overlap_and_dependency(self) -> None:
        """Inv 2 — no shared path, no dep graph ⇒ overlap and dependency channels are 0."""
        result = collision_risk(_ws("a", "research.findings"), _ws("b", "draft.outline"))
        assert result.channels.overlap == 0.0
        assert result.channels.dependency == 0.0

    def test_identical_path_positive_overlap(self) -> None:
        """Inv 3 — identical write path ⇒ overlap channel > 0."""
        result = collision_risk(_ws("a", "draft.body"), _ws("b", "draft.body"))
        assert result.channels.overlap > 0.0

    def test_nested_path_positive_overlap(self) -> None:
        """Inv 3 — ancestor/nested write path ⇒ overlap channel > 0."""
        result = collision_risk(_ws("a", "draft"), _ws("b", "draft.body.intro"))
        assert result.channels.overlap > 0.0

    def test_dependency_channel_zero_without_graph(self) -> None:
        result = collision_risk(_ws("a", "x.y"), _ws("b", "p.q"))
        assert result.channels.dependency == 0.0

    def test_dependency_channel_fires_with_graph(self) -> None:
        """Injected dep distance of 1 hop ⇒ dependency channel > 0 even for disjoint paths."""

        def dep_distance(a: str, b: str) -> float:
            return 1.0  # direct edge both ways

        result = collision_risk(_ws("a", "module_x"), _ws("b", "module_y"), dep_distance=dep_distance)
        assert result.channels.dependency > 0.0


class TestAdviseAndPriority:
    def test_clear_when_disjoint(self) -> None:
        """Inv 5 — low risk ⇒ CLEAR with no steer/hold and transmit False."""
        policy = TcasCollisionPolicy()
        adv = policy.advise(_ws("a", "research.findings"), _ws("b", "draft.outline"))
        assert adv.level is AdvisoryLevel.CLEAR
        assert adv.steer is None and adv.hold is None
        assert adv.transmit is False

    def test_resolution_on_identical_path(self) -> None:
        """Inv 6 — identical write path ⇒ RESOLUTION_ADVISORY, exactly one steer + one hold."""
        policy = TcasCollisionPolicy()
        adv = policy.advise(_ws("a", "draft.body"), _ws("b", "draft.body"))
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY
        assert adv.transmit is True
        assert {adv.steer, adv.hold} == {"a", "b"}
        assert adv.steer != adv.hold

    def test_higher_progress_holds_right_of_way(self) -> None:
        """Priority signal 1 — more committed write weight holds (at resolution level)."""
        # Both fully overlap "draft.body" (risk → RA); high has more committed progress.
        high = AgentWriteSet("a", (WriteItem("draft.body", 1.0), WriteItem("draft.notes", 1.0)))
        low = AgentWriteSet("b", (WriteItem("draft.body", 1.0),))
        policy = TcasCollisionPolicy()
        adv = policy.advise(high, low)
        assert adv.level is AdvisoryLevel.RESOLUTION_ADVISORY
        assert adv.hold == "a"
        assert adv.steer == "b"

    def test_advise_is_symmetric(self) -> None:
        """Inv 4 — advise(a,b) and advise(b,a) agree on level + hold/steer assignment."""
        policy = TcasCollisionPolicy()
        a = _ws("agent_a", "draft.body", started_at=100.0)
        b = _ws("agent_b", "draft.body", started_at=200.0)
        ab = policy.advise(a, b)
        ba = policy.advise(b, a)
        assert ab.level is ba.level
        assert ab.hold == ba.hold
        assert ab.steer == ba.steer

    def test_priority_tiebreak_is_total(self) -> None:
        """Inv 7 — equal progress + equal start ⇒ agent_id breaks the tie deterministically."""
        a = _ws("agent_a", "draft.body")
        b = _ws("agent_b", "draft.body")
        assert has_right_of_way(a, b) is True  # "agent_a" < "agent_b"
        assert has_right_of_way(b, a) is False

    def test_earlier_start_holds_when_progress_equal(self) -> None:
        a = _ws("z_agent", "draft.body", started_at=100.0)  # earlier
        b = _ws("a_agent", "draft.body", started_at=200.0)
        # earlier start beats lexicographic agent_id
        assert has_right_of_way(a, b) is True

    def test_policy_satisfies_protocol(self) -> None:
        assert isinstance(TcasCollisionPolicy(), CollisionPolicy)

    def test_invalid_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            TcasCollisionPolicy(tau_traffic=0.8, tau_resolution=0.3)

    def test_symmetry_on_progress_tier(self) -> None:
        """Inv 4 / Property 2 — symmetry holds when the dominant (progress) tier decides."""
        high = AgentWriteSet("a", (WriteItem("draft.body", 1.0), WriteItem("draft.notes", 1.0)))
        low = AgentWriteSet("b", (WriteItem("draft.body", 1.0),))
        policy = TcasCollisionPolicy()
        ab = policy.advise(high, low)
        ba = policy.advise(low, high)
        assert ab.level is ba.level is AdvisoryLevel.RESOLUTION_ADVISORY
        assert ab.hold == ba.hold == "a"
        assert ab.steer == ba.steer == "b"

    def test_advise_is_idempotent(self) -> None:
        """Determinism — identical inputs yield an identical advisory across calls."""
        policy = TcasCollisionPolicy()
        a = _ws("a", "draft.body", started_at=1.0)
        b = _ws("b", "draft.body", started_at=2.0)
        assert policy.advise(a, b) == policy.advise(a, b)

    def test_unknown_start_sorts_last(self) -> None:
        """has_right_of_way — a known start (>0) beats an unknown start (0.0)."""
        unknown = _ws("z_agent", "draft.body", started_at=0.0)
        known = _ws("a_agent", "draft.body", started_at=50.0)
        assert has_right_of_way(known, unknown) is True
        assert has_right_of_way(unknown, known) is False

    def test_shared_agent_id_rejected(self) -> None:
        """has_right_of_way requires distinct agent_ids to stay a total order."""
        a = _ws("same", "draft.body")
        b = _ws("same", "draft.notes")
        with pytest.raises(ValueError):
            has_right_of_way(a, b)

    def test_threshold_boundaries(self) -> None:
        """Band edges — comparison is strict `<`, so risk == tau lands in the HIGHER band."""
        # Sibling paths give a deterministic risk strictly between 0 and 1 (overlap 0, tree > 0).
        a = _ws("a", "draft.body")
        b = _ws("b", "draft.notes")
        risk = collision_risk(a, b).risk
        assert 0.0 < risk < 1.0

        # risk == tau_resolution ⇒ NOT (risk < tau) ⇒ RESOLUTION.
        at_ra = TcasCollisionPolicy(tau_traffic=risk / 2, tau_resolution=risk)
        assert at_ra.advise(a, b).level is AdvisoryLevel.RESOLUTION_ADVISORY

        # tau_resolution just above risk ⇒ risk < tau ⇒ steps down to TRAFFIC.
        below_ra = TcasCollisionPolicy(tau_traffic=risk / 2, tau_resolution=risk + 1e-6)
        assert below_ra.advise(a, b).level is AdvisoryLevel.TRAFFIC_ADVISORY

        # risk == tau_traffic ⇒ NOT (risk < tau_traffic) ⇒ TRAFFIC (not CLEAR).
        at_ta = TcasCollisionPolicy(tau_traffic=risk, tau_resolution=1.0)
        assert at_ta.advise(a, b).level is AdvisoryLevel.TRAFFIC_ADVISORY

        # tau_traffic just above risk ⇒ risk < tau_traffic ⇒ CLEAR.
        below_ta = TcasCollisionPolicy(tau_traffic=risk + 1e-6, tau_resolution=1.0)
        assert below_ta.advise(a, b).level is AdvisoryLevel.CLEAR

    def test_dependency_unreachable_yields_zero(self) -> None:
        """dep_distance returning inf (unreachable) ⇒ dependency channel 0, no crash."""
        result = collision_risk(_ws("a", "x"), _ws("b", "y"), dep_distance=lambda _a, _b: float("inf"))
        assert result.channels.dependency == 0.0

    def test_invalid_gamma_rejected(self) -> None:
        with pytest.raises(ValueError):
            collision_risk(_ws("a", "x"), _ws("b", "x"), gamma=1.5)

    def test_empty_write_set_is_clear(self) -> None:
        result = collision_risk(_ws("a"), _ws("b", "draft.body"))
        assert result.risk == 0.0
        assert TcasCollisionPolicy().advise(_ws("a"), _ws("b")).level is AdvisoryLevel.CLEAR


class TestClamp01:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (float("nan"), 0.0),
            (float("inf"), 0.0),
            (float("-inf"), 0.0),
            (-0.5, 0.0),
            (1.5, 1.0),
            (0.42, 0.42),
        ],
    )
    def test_clamp01(self, value: float, expected: float) -> None:
        assert clamp01(value) == expected

    def test_nan_weight_keeps_risk_bounded(self) -> None:
        """A malformed NaN weight must not escape the [0,1] bound."""
        bad = AgentWriteSet("a", (WriteItem("draft.body", float("nan")),))
        result = collision_risk(bad, _ws("b", "draft.body"))
        assert 0.0 <= result.risk <= 1.0


# Seeded property table — diverse path-set shapes; bounds + symmetry hold for every pair.
_PAIRS = [
    (("research.findings",), ("draft.outline",)),  # disjoint
    (("draft.body",), ("draft.body",)),  # identical
    (("draft",), ("draft.body.intro",)),  # nested
    (("draft.body",), ("draft.notes",)),  # sibling
    (("a.b.c.d",), ("a.b.c.e",)),  # deep nest
    (("draft.body", "draft.notes"), ("draft.body",)),  # multi-item
    ((), ("draft.body",)),  # empty vs non-empty
]


@pytest.mark.parametrize(("a_paths", "b_paths"), _PAIRS)
def test_property_bounds_and_symmetry(a_paths: tuple[str, ...], b_paths: tuple[str, ...]) -> None:
    """Property — for every shape: risk bounded, distance dual, advise symmetric."""
    a = AgentWriteSet("agent_a", tuple(WriteItem(p) for p in a_paths))
    b = AgentWriteSet("agent_b", tuple(WriteItem(p) for p in b_paths))
    result = collision_risk(a, b)
    assert 0.0 <= result.risk <= 1.0
    assert result.distance == pytest.approx(1.0 - result.risk)
    policy = TcasCollisionPolicy()
    ab, ba = policy.advise(a, b), policy.advise(b, a)
    assert ab.level is ba.level
    assert ab.hold == ba.hold
    assert ab.steer == ba.steer
