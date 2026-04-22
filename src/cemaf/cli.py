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

    bp_parser = subparsers.add_parser(
        "blueprint",
        help="Inspect the curated blueprint library (from CEMAF_BLUEPRINT_CATALOG)",
    )
    bp_sub = bp_parser.add_subparsers(dest="blueprint_command")

    bp_list = bp_sub.add_parser("list", help="List all entries in the library")
    bp_list.add_argument(
        "--kind",
        choices=["snapshot", "factory", "recipe"],
        action="append",
        help="Filter by entry kind (repeatable)",
    )

    bp_search = bp_sub.add_parser("search", help="Keyword search the blueprint library")
    bp_search.add_argument("query", nargs="+", help="Search query")
    bp_search.add_argument("-k", type=int, default=5, help="Max results (default 5)")
    bp_search.add_argument(
        "--kind",
        choices=["snapshot", "factory", "recipe"],
        action="append",
        help="Filter by entry kind (repeatable)",
    )
    bp_search.add_argument(
        "--tag",
        action="append",
        help="Require at least one of the given tags (repeatable)",
    )

    bp_show = bp_sub.add_parser("show", help="Resolve an entry and print its prompt")
    bp_show.add_argument("entry_id", help="Blueprint entry id")

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
    elif args.command == "blueprint":
        sub = getattr(args, "blueprint_command", None)
        if sub == "list":
            _blueprint_list(kinds=tuple(args.kind) if args.kind else None)
        elif sub == "search":
            _blueprint_search(
                query=" ".join(args.query),
                k=args.k,
                kinds=tuple(args.kind) if args.kind else None,
                tags=tuple(args.tag) if args.tag else None,
            )
        elif sub == "show":
            _blueprint_show(entry_id=args.entry_id)
        else:
            bp_parser.print_help()
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


def _blueprint_list(*, kinds: tuple[str, ...] | None) -> None:
    """Print every entry in the env-configured library."""
    from cemaf.blueprint.factories import create_blueprint_library_from_env
    from cemaf.blueprint.library import BlueprintEntryKind

    library = create_blueprint_library_from_env()
    if len(library) == 0:
        print("Library is empty. Set CEMAF_BLUEPRINT_CATALOG to a JSON catalog path.")
        return

    kind_filter: set[BlueprintEntryKind] | None = None
    if kinds:
        kind_filter = {BlueprintEntryKind(k) for k in kinds}

    shown = 0
    for entry in library:
        if kind_filter is not None and entry.kind not in kind_filter:
            continue
        print(f"  [{entry.kind.value:<8}]  {entry.title}")
        print(f"              id: {entry.id}")
        if entry.tags:
            print(f"              tags: {', '.join(entry.tags)}")
        print()
        shown += 1
    print(f"{shown} shown, {len(library)} total")


def _blueprint_search(
    *,
    query: str,
    k: int,
    kinds: tuple[str, ...] | None,
    tags: tuple[str, ...] | None,
) -> None:
    """Search the env-configured library."""
    from cemaf.blueprint.factories import create_blueprint_library_from_env
    from cemaf.blueprint.library import BlueprintEntryKind

    library = create_blueprint_library_from_env()
    kind_filter: tuple[BlueprintEntryKind, ...] | None = None
    if kinds:
        kind_filter = tuple(BlueprintEntryKind(k) for k in kinds)

    results = library.search(query=query, k=k, kinds=kind_filter, tags=tags)
    if not results:
        print(f"No matches for: {query}")
        return
    print(f"Query: {query}   ({len(results)} result(s), library size {len(library)})\n")
    for entry, score in results:
        print(f"  [{score:5.1f}]  {entry.kind.value:<8}  {entry.title}")
        print(f"            id: {entry.id}")
        if entry.tags:
            print(f"            tags: {', '.join(entry.tags)}")
        print()
    print("Show prompt:  cemaf blueprint show <id>")


def _blueprint_show(*, entry_id: str) -> None:
    """Resolve an entry and print its rendered prompt."""
    from cemaf.blueprint.factories import create_blueprint_library_from_env
    from cemaf.blueprint.library import BlueprintNotFound, BlueprintResolutionError

    library = create_blueprint_library_from_env()
    try:
        blueprint = library.resolve(entry_id=entry_id)
    except BlueprintNotFound:
        print(f"No entry with id: {entry_id}")
        return
    except BlueprintResolutionError as exc:
        print(f"Entry {entry_id!r} failed to resolve: {exc}")
        return

    entry = library.get(entry_id)
    assert entry is not None
    print(f"# {entry.title}")
    print(f"id:     {entry.id}")
    print(f"kind:   {entry.kind.value}")
    print(f"source: {entry.source}")
    if entry.tags:
        print(f"tags:   {', '.join(entry.tags)}")
    print()
    print("--- Rendered Prompt ---")
    print(blueprint.to_prompt())


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
