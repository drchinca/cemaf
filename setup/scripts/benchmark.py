#!/usr/bin/env python3
"""Benchmarking utilities using pytest-benchmark.

This script helps run and compare performance benchmarks.

Usage:
    python scripts/benchmark.py                    # Run all benchmarks
    python scripts/benchmark.py --save baseline    # Save baseline
    python scripts/benchmark.py --compare baseline # Compare with baseline
    python scripts/benchmark.py --list             # List saved benchmarks
"""

import argparse
import json
import subprocess  # nosec B404
import sys
from pathlib import Path


def run_benchmarks(
    compare: str | None = None,
    save: str | None = None,
    verbose: bool = False,
) -> None:
    """Run benchmark tests.

    Args:
        compare: Name of saved benchmark to compare against
        save: Name to save benchmark results as
        verbose: Enable verbose output
    """
    cmd = [
        "pytest",
        "tests/",
        "-m",
        "benchmark",
        "--benchmark-only",
        "--benchmark-sort=mean",
        "--benchmark-columns=min,max,mean,stddev,ops",
    ]

    if verbose:
        cmd.append("-vv")

    if compare:
        cmd.extend(["--benchmark-compare", compare])
        cmd.append("--benchmark-compare-fail=mean:10%")  # Fail if >10% slower

    if save:
        cmd.extend(["--benchmark-save", save])

    print("🔧 Running benchmarks...")
    print(f"   Command: {' '.join(cmd)}")
    print()

    try:
        subprocess.run(cmd, check=True)  # nosec B603
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Benchmarks failed with exit code {e.returncode}")
        sys.exit(e.returncode)


def list_benchmarks() -> None:
    """List available benchmark comparisons."""
    benchmark_dir = Path(".benchmarks")

    if not benchmark_dir.exists():
        print("📊 No benchmarks found.")
        print("   Run benchmarks with --save option to create baseline:")
        print("   python scripts/benchmark.py --save baseline")
        return

    print("\n📊 Available benchmark results:\n")

    found_any = False
    for platform_dir in sorted(benchmark_dir.iterdir()):
        if not platform_dir.is_dir():
            continue

        results = sorted(platform_dir.glob("*.json"))
        if not results:
            continue

        found_any = True
        print(f"  Platform: {platform_dir.name}")

        for result_file in results:
            # Load and display summary
            try:
                with open(result_file) as f:
                    data = json.load(f)
                    benchmarks = data.get("benchmarks", [])
                    timestamp = data.get("datetime", "unknown")
                    print(f"    - {result_file.stem}")
                    print(f"      Date: {timestamp}")
                    print(f"      Tests: {len(benchmarks)}")
            except Exception as e:
                print(f"    - {result_file.stem} (error reading: {e})")
        print()

    if not found_any:
        print("  No benchmark results found.")
        print("  Run benchmarks with --save to create results.")


def main() -> None:
    """Run benchmarking based on CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Run and compare performance benchmarks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all benchmarks
  python scripts/benchmark.py

  # Save baseline for future comparisons
  python scripts/benchmark.py --save baseline

  # Compare current performance against baseline
  python scripts/benchmark.py --compare baseline

  # List saved benchmark results
  python scripts/benchmark.py --list

Note: Requires pytest-benchmark to be installed.
  Install with: uv pip install pytest-benchmark
        """,
    )

    parser.add_argument(
        "--compare",
        metavar="NAME",
        help="Compare with saved benchmark",
    )
    parser.add_argument(
        "--save",
        metavar="NAME",
        help="Save benchmark results with this name",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available benchmarks",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.list:
        list_benchmarks()
    else:
        run_benchmarks(
            compare=args.compare,
            save=args.save,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
