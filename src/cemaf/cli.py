"""CEMAF CLI — inspect registered agents, tools, and DAGs."""

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

    # cemaf inspect
    subparsers.add_parser("inspect", help="Show framework capabilities")

    args = parser.parse_args()

    if args.command == "inspect":
        _inspect()
    else:
        parser.print_help()


def _inspect() -> None:
    """Show framework module overview."""

    print(f"CEMAF v{__version__}")
    print()
    print("Modules:")
    modules = [
        "agents",
        "tools",
        "skills",
        "orchestration",
        "context",
        "memory",
        "llm",
        "evals",
        "events",
        "observability",
        "resilience",
        "meta (self-hosting)",
        "audit",
        "knowledge",
        "scheduler",
    ]
    for m in modules:
        print(f"  - {m}")

    print()
    print("Entry points:")
    print("  cemaf.create_executor(agent_registry=...) -> DAGExecutor")
    print("  cemaf.meta.bootstrap.create_meta_executor(...) -> DAGExecutor (self-hosting)")
    print()
    print("Quick start:")
    print("  from cemaf import create_executor, AgentRegistry, DAG")


if __name__ == "__main__":
    main()
