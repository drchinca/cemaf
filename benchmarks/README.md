# CEMAF Benchmarks

This directory contains a local benchmark and veracity harness for CEMAF's public capability statements.

Run the fast local check:

```bash
uv run python benchmarks/run_benchmarks.py
```

Generate durable local evidence:

```bash
uv run python benchmarks/run_benchmarks.py \
  --json-out benchmarks/results/local-baseline.json \
  --markdown-out benchmarks/results/local-baseline.md
```

The harness reports two kinds of evidence:

- `veracity_checks`: executable checks tied to README/docs capability statements, including DAG
  execution, pull-cost behavior, token-budget context selection, patch provenance, event delivery,
  shared-executor concurrency isolation, auction selection, council voting, gate interception,
  citation provenance, blueprint harvesting, and RLM large-context retrieval/concurrency accuracy.
- `benchmarks`: timing numbers with repeated samples, mean, median, p95, throughput, iteration count, and environment metadata.

The numbers are machine-local. Use them as reproducible evidence for the current checkout, not as universal performance guarantees.
