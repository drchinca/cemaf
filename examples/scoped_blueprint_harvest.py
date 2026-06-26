"""
CEMAF Scoped Blueprint Harvest — per-project learning + PROJECT→GLOBAL promotion (SPEC-13).

Harvested blueprints are scoped to the project they came from, so the same goal learned in two
projects produces two distinct entries (no cross-project clobber). A blueprint is promoted to
GLOBAL — usable everywhere — only once it has proven itself in ≥2 distinct projects at mean
confidence ≥0.8.

Usage:
    uv run python examples/scoped_blueprint_harvest.py
"""

import asyncio

from cemaf.blueprint import evaluate_promotion
from cemaf.blueprint.harvest import HarvestContext
from cemaf.blueprint.harvest_defaults import ProjectScopedRecipeDistiller
from cemaf.events.protocols import Event, EventType

_GOAL = "summarize the quarterly report"


async def main() -> None:
    event = Event.create(type=EventType.EVAL_COMPLETED, payload={"overall_score": 0.85})
    context = HarvestContext(run_id="r", node_id="n", goal_text=_GOAL, output_text="…")

    # The SAME goal harvested in two different projects → two distinct, non-clobbering entries.
    alpha_entry = await ProjectScopedRecipeDistiller(project_id="alpha").distill(event=event, context=context)
    beta_entry = await ProjectScopedRecipeDistiller(project_id="beta").distill(event=event, context=context)
    assert alpha_entry is not None and beta_entry is not None

    print("Same goal, two projects → distinct ids (no clobber):")
    print(f"  alpha: {alpha_entry.id}  (project_id={alpha_entry.project_id}, "
          f"scope={alpha_entry.scope.value})")
    print(f"  beta:  {beta_entry.id}  (project_id={beta_entry.project_id}, "
          f"scope={beta_entry.scope.value})")

    # Promotion: proven across ≥2 distinct projects at mean confidence ≥0.8 → GLOBAL candidate.
    decisions = evaluate_promotion((alpha_entry, beta_entry))
    promoted = [d for d in decisions if d.promote]
    print(f"\nPromotion over the two entries: promote={bool(promoted)}")
    if promoted:
        d = promoted[0]
        print(f"  → blueprint {d.blueprint_key} proven in {d.project_ids} "
              f"(mean confidence {d.mean_confidence:.2f}) → eligible for GLOBAL scope")


if __name__ == "__main__":
    asyncio.run(main())
