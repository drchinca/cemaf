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

    args = parser.parse_args()

    if args.command == "inspect":
        _inspect()
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
