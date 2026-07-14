"""Stress the disposable-worker/durable-companion CEMAF app shape."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.app_shapes.disposable_workers_durable_companion import run_experiment


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--workers", type=int, choices=(2, 3), default=3)
    args = parser.parse_args()
    logging.getLogger("cemaf").setLevel(logging.WARNING)

    with TemporaryDirectory(prefix="cemaf-worker-stress-") as root:
        summary = await run_experiment(
            root=root,
            run_count=args.runs,
            worker_count=args.workers,
        )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
