#!/usr/bin/env python3
"""Performance profiling script.

Provides multiple profiling modes for analyzing code performance.

Usage:
    python scripts/profile.py <module.function>
    python scripts/profile.py --memory <module.function>
    python scripts/profile.py --line-by-line <module.function>

Examples:
    python scripts/profile.py cemaf.main.main
    python scripts/profile.py --memory cemaf.main.process_data
    python scripts/profile.py --line-by-line cemaf.main.calculate
"""

import argparse
import cProfile
import pstats
import sys
from io import StringIO
from pathlib import Path


def profile_function(func_path: str, output_file: str | None = None) -> None:
    """Profile a function using cProfile.

    Args:
        func_path: Dotted path to function (e.g., module.function)
        output_file: Optional file to save results
    """
    # Import the function
    module_path, func_name = func_path.rsplit(".", 1)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    try:
        module = __import__(module_path, fromlist=[func_name])
        func = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        print(f"❌ Error importing {func_path}: {e}")
        sys.exit(1)

    # Profile the function
    profiler = cProfile.Profile()
    profiler.enable()

    try:
        result = func()
        print(f"✅ Function result: {result}")
    except Exception as e:
        print(f"❌ Function raised exception: {e}")
    finally:
        profiler.disable()

    # Generate statistics
    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.strip_dirs()
    stats.sort_stats("cumulative")
    stats.print_stats(30)  # Top 30 functions

    output = stream.getvalue()
    print("\n" + "=" * 80)
    print("PROFILING RESULTS (Top 30 functions by cumulative time)")
    print("=" * 80)
    print(output)

    if output_file:
        with open(output_file, "w") as f:
            f.write(output)
        print(f"\n📊 Results saved to: {output_file}")


def memory_profile(func_path: str) -> None:
    """Profile memory usage using memory_profiler.

    Args:
        func_path: Dotted path to function
    """
    try:
        from memory_profiler import profile as mem_profile
    except ImportError:
        print("❌ memory_profiler not installed")
        print("Install with: uv pip install memory-profiler")
        sys.exit(1)

    module_path, func_name = func_path.rsplit(".", 1)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    try:
        module = __import__(module_path, fromlist=[func_name])
        func = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        print(f"❌ Error importing {func_path}: {e}")
        sys.exit(1)

    # Apply memory profiler decorator
    profiled_func = mem_profile(func)
    print("\n" + "=" * 80)
    print("MEMORY PROFILING RESULTS")
    print("=" * 80)
    profiled_func()


def line_profile(func_path: str) -> None:
    """Profile line-by-line execution using line_profiler.

    Args:
        func_path: Dotted path to function
    """
    try:
        from line_profiler import LineProfiler
    except ImportError:
        print("❌ line_profiler not installed")
        print("Install with: uv pip install line-profiler")
        sys.exit(1)

    module_path, func_name = func_path.rsplit(".", 1)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    try:
        module = __import__(module_path, fromlist=[func_name])
        func = getattr(module, func_name)
    except (ImportError, AttributeError) as e:
        print(f"❌ Error importing {func_path}: {e}")
        sys.exit(1)

    # Profile line by line
    profiler = LineProfiler()
    profiler.add_function(func)
    profiler.enable()

    try:
        func()
    except Exception as e:
        print(f"❌ Function raised exception: {e}")
    finally:
        profiler.disable()
        print("\n" + "=" * 80)
        print("LINE-BY-LINE PROFILING RESULTS")
        print("=" * 80)
        profiler.print_stats()


def main() -> None:
    """Run profiling based on CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Profile Python code performance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/profile.py cemaf.main.main
  python scripts/profile.py --memory cemaf.main.process
  python scripts/profile.py --line-by-line cemaf.main.calculate
        """,
    )
    parser.add_argument(
        "function",
        help="Function to profile (module.path.function)",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Profile memory usage",
    )
    parser.add_argument(
        "--line-by-line",
        action="store_true",
        help="Line-by-line profiling",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file for results (cProfile mode only)",
    )

    args = parser.parse_args()

    print(f"🔍 Profiling: {args.function}")
    print()

    if args.memory:
        memory_profile(args.function)
    elif args.line_by_line:
        line_profile(args.function)
    else:
        profile_function(args.function, args.output)


if __name__ == "__main__":
    main()
