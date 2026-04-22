"""CEMAF CLI — inspect framework capabilities."""

import argparse

from cemaf import __version__


def main() -> None:
    """Entry point for the cemaf CLI."""
    parser = argparse.ArgumentParser(
        prog="cemaf",
        description="CEMAF — Context Engineering Multi-Agent Framework",
    )
    parser.add_argument("--version", action="version", version=f"cemaf {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("inspect", help="Introspect framework protocols, node types, and eval metrics")

    docs_parser = subparsers.add_parser(
        "docs",
        help="Query CEMAF's own docs + docstrings (for LLMs and humans)",
    )
    docs_sub = docs_parser.add_subparsers(dest="docs_command")

    docs_search = docs_sub.add_parser("search", help="Keyword search the docs index")
    docs_search.add_argument("query", nargs="+", help="Search query")
    docs_search.add_argument("-k", type=int, default=5, help="Max results (default 5)")
    docs_search.add_argument(
        "--kind",
        choices=["guide", "package", "module", "pattern", "spec"],
        action="append",
        help="Filter by kind (repeatable)",
    )

    docs_show = docs_sub.add_parser("show", help="Print the full body of one entry")
    docs_show.add_argument("entry_id", help="Entry id (e.g. docs/architecture.md)")

    docs_sub.add_parser(
        "serve",
        help="Run an MCP stdio server exposing the docs to any MCP client",
    )

    args = parser.parse_args()

    if args.command == "inspect":
        _inspect()
    elif args.command == "docs":
        sub = getattr(args, "docs_command", None)
        if sub == "search":
            _docs_search(
                query=" ".join(args.query),
                k=args.k,
                kinds=tuple(args.kind) if args.kind else None,
            )
        elif sub == "show":
            _docs_show(entry_id=args.entry_id)
        elif sub == "serve":
            _docs_serve()
        else:
            docs_parser.print_help()
    else:
        parser.print_help()


def _inspect() -> None:
    """Dynamically introspect and display framework capabilities."""
    from cemaf.core.enums import MemoryScope, NodeType, ToolRiskLevel
    from cemaf.evals.protocols import EvalMetric

    print(f"CEMAF v{__version__}")
    print()

    # Node types — from actual enum
    print("Node Types:")
    for nt in NodeType:
        print(f"  {nt.value}")

    print()
    print("Tool Risk Levels:")
    for rl in ToolRiskLevel:
        print(f"  {rl.value}")

    print()
    print("Eval Metrics:")
    for em in EvalMetric:
        print(f"  {em.value}")

    print()
    print("Memory Scopes:")
    for ms in MemoryScope:
        print(f"  {ms.value}")

    print()
    print("Protocols (bring your own):")
    _list_protocols()

    print()
    print("Entry points:")
    print("  cemaf.create_executor(agent_registry=...) -> DAGExecutor")
    print("  cemaf.meta.bootstrap.create_meta_executor(...) -> DAGExecutor")
    print()
    print("Quick start:")
    print("  from cemaf import create_executor, AgentRegistry, DAG, Node")
    print("  See: examples/hello_world.py")


def _docs_search(
    *,
    query: str,
    k: int,
    kinds: tuple[str, ...] | None,
) -> None:
    """Search CEMAF docs and print ranked results."""
    from cemaf.docs_api import build_default_index
    from cemaf.docs_api.index import DocEntryKind

    index = build_default_index()
    kind_filter: tuple[DocEntryKind, ...] | None = None
    if kinds:
        kind_filter = tuple(DocEntryKind(k) for k in kinds)

    results = index.search(query=query, k=k, kinds=kind_filter)
    if not results:
        print(f"No matches for: {query}")
        return
    print(f"Query: {query}   ({len(results)} result(s), index size {len(index)})\n")
    for entry, score in results:
        print(f"  [{score:5.1f}]  {entry.kind.value:<8}  {entry.title}")
        print(f"            id: {entry.id}")
        if entry.anchors:
            print(f"            anchors: {', '.join(entry.anchors[:3])}")
        print()
    print("Show full body:  cemaf docs show <id>")


def _docs_show(*, entry_id: str) -> None:
    """Print one entry's full body."""
    from cemaf.docs_api import build_default_index

    index = build_default_index()
    entry = index.get(entry_id)
    if entry is None:
        print(f"No entry with id: {entry_id}")
        return
    print(f"# {entry.title}")
    print(f"id:     {entry.id}")
    print(f"kind:   {entry.kind.value}")
    print(f"source: {entry.source}")
    if entry.path:
        print(f"path:   {entry.path}")
    print()
    print(entry.body)


def _docs_serve() -> None:
    """Run an MCP stdio server exposing the CEMAF docs index."""
    import asyncio

    from cemaf.docs_api import build_default_index
    from cemaf.docs_api.mcp_server import create_docs_mcp_server
    from cemaf.mcp.transport.stdio import StdioTransport

    index = build_default_index()
    server = create_docs_mcp_server(index=index, transport=StdioTransport())
    asyncio.run(server.serve())


def _list_protocols() -> None:
    """Discover @runtime_checkable protocols from key modules."""
    import inspect

    from cemaf import agents, context, evals, events, llm, memory, tools

    modules = [agents, tools, evals, context, llm, memory, events]
    seen: set[str] = set()

    for mod in modules:
        for name in dir(mod):
            obj = getattr(mod, name)
            if inspect.isclass(obj) and hasattr(obj, "__protocol_attrs__") and name not in seen:
                seen.add(name)
                mod_name = getattr(mod, "__name__", "")
                short = mod_name.replace("cemaf.", "")
                print(f"  {short}.{name}")


if __name__ == "__main__":
    main()
