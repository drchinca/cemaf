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
        help="Search CEMAF's own docs + docstrings (for LLMs and humans)",
    )
    docs_parser.add_argument("query", nargs="+", help="Search query")
    docs_parser.add_argument("-k", type=int, default=5, help="Max results (default 5)")
    docs_parser.add_argument(
        "--kind",
        choices=["guide", "package", "module", "pattern", "spec"],
        action="append",
        help="Filter by kind (repeatable)",
    )
    docs_parser.add_argument(
        "--show",
        metavar="ID",
        help="Print full body for a specific entry id (skips search)",
    )

    args = parser.parse_args()

    if args.command == "inspect":
        _inspect()
    elif args.command == "docs":
        _docs(
            query=" ".join(args.query) if args.query else "",
            k=args.k,
            kinds=tuple(args.kind) if args.kind else None,
            show=args.show,
        )
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


def _docs(
    *,
    query: str,
    k: int,
    kinds: tuple[str, ...] | None,
    show: str | None,
) -> None:
    """Search CEMAF docs or show a specific entry."""
    from cemaf.docs_api import build_default_index
    from cemaf.docs_api.index import DocEntryKind

    index = build_default_index()

    if show:
        entry = index.get(show)
        if entry is None:
            print(f"No entry with id: {show}")
            return
        print(f"# {entry.title}")
        print(f"id:     {entry.id}")
        print(f"kind:   {entry.kind.value}")
        print(f"source: {entry.source}")
        if entry.path:
            print(f"path:   {entry.path}")
        print()
        print(entry.body)
        return

    if not query:
        print("Usage: cemaf docs <query> [-k N] [--kind guide|package|module|pattern]")
        print("       cemaf docs --show <entry-id>")
        print(f"\nIndex size: {len(index)} entries")
        return

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
    print("Show full body:  cemaf docs --show <id>")


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
