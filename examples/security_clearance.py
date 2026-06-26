"""
CEMAF Context Security Classification — clearance-gated compilation (SPEC-11).

Every context source can carry a SecurityLevel (PUBLIC / INTERNAL / CONFIDENTIAL). When the
compiler runs with a caller `clearance`, sources above that clearance are dropped BEFORE
selection — so a CONFIDENTIAL datum never reaches a prompt assembled for a lower-clearance
call, and the freed budget goes to content the caller is allowed to see.

Usage:
    uv run python examples/security_clearance.py
"""

import asyncio

from cemaf.context import PriorityContextCompiler, SecurityLevel, TokenBudget
from cemaf.context.compiler import SimpleTokenEstimator


async def main() -> None:
    compiler = PriorityContextCompiler(token_estimator=SimpleTokenEstimator(chars_per_token=4.0))

    # Two artifacts; "secret" is CONFIDENTIAL and would win on priority if ungated.
    artifacts = (("secret", "internal financials…"), ("notes", "public summary…"))
    source_levels = {"secret": SecurityLevel.CONFIDENTIAL, "notes": SecurityLevel.PUBLIC}
    budget = TokenBudget(max_tokens=1000, reserved_for_output=0)
    priorities = {"secret": 100, "notes": 1}

    # Caller with full clearance sees everything.
    full = await compiler.compile(
        artifacts=artifacts, memories=(), budget=budget, priorities=priorities,
        source_levels=source_levels, clearance=SecurityLevel.CONFIDENTIAL,
    )
    print(f"CONFIDENTIAL clearance → sources: {sorted(s.key for s in full.sources)}")

    # Caller with only INTERNAL clearance: the CONFIDENTIAL source is gated out.
    limited = await compiler.compile(
        artifacts=artifacts, memories=(), budget=budget, priorities=priorities,
        source_levels=source_levels, clearance=SecurityLevel.INTERNAL,
    )
    print(f"INTERNAL clearance    → sources: {sorted(s.key for s in limited.sources)}")
    print(f"  excluded by classification: {limited.metadata['security_excluded']}")

    # No clearance set → ungated, exactly the pre-SPEC-11 behavior.
    ungated = await compiler.compile(
        artifacts=artifacts, memories=(), budget=budget, priorities=priorities,
    )
    print(f"no clearance (ungated)→ sources: {sorted(s.key for s in ungated.sources)}")


if __name__ == "__main__":
    asyncio.run(main())
