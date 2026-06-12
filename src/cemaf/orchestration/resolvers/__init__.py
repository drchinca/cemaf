"""NodeResolvers — one seam, one decision per resolver, registered in order.

The seam replaces the three bespoke ``if`` branches in ``execute_node`` (council
node? auction node? static ref?). Each resolver answers ONE question: given a
node + context, what is the next step? Either the executor should run a named
agent (``RunAgent``), or the node is already fully resolved (``NodeComplete``,
e.g. a council that returns its own NodeResult). The executor picks the first
resolver whose ``matches(node)`` returns True; the rest is uniform dispatch.

Adding a new node kind (e.g. a future CouncilOfSelectors) is registering a new
resolver — the executor never grows a new branch.
"""

from cemaf.orchestration.resolvers.auction import AuctionResolver
from cemaf.orchestration.resolvers.council import CouncilResolver
from cemaf.orchestration.resolvers.protocols import (
    NodeComplete,
    NodeResolver,
    ResolveOutcome,
    RunAgent,
)
from cemaf.orchestration.resolvers.static_ref import StaticRefResolver

__all__ = [
    "AuctionResolver",
    "CouncilResolver",
    "NodeComplete",
    "NodeResolver",
    "ResolveOutcome",
    "RunAgent",
    "StaticRefResolver",
]
