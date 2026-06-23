# CEMAF Makefile — one entry point for the workflows scattered across docs.
#
# Run `make` (no args) for the menu. Every target is a thin wrapper around the
# command already documented somewhere under `docs/`. Nothing here is magic —
# you can copy any recipe line into a terminal and it will run unchanged.

.PHONY: help install test test-unit test-integration coverage lint typecheck format \
        benchmark benchmark-report \
        check audit-links audit-graph audit-traces audit-all \
        demo demo-step traces showcase docs-search clean

# ---- self-documenting menu -------------------------------------------------

help:  ## Print this menu (default target)
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / { \
		printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 \
	}' $(MAKEFILE_LIST)
	@echo
	@echo "  Quick wins:"
	@echo "    make install      # uv sync --extra dev"
	@echo "    make check        # all doc + code audits (CI-equivalent)"
	@echo "    make demo         # regenerate 7 real CEMAF traces"
	@echo "    make showcase     # open the interactive demo in your browser"

# ---- environment -----------------------------------------------------------

install:  ## uv sync the dev extra
	uv sync --extra dev

# ---- tests + code quality --------------------------------------------------

test:  ## All tests (unit + integration)
	uv run pytest -v

test-unit:  ## Just the unit tests (fast)
	uv run pytest tests/unit/ -v

test-integration:  ## Just the integration tests
	uv run pytest tests/integration/ -v

coverage:  ## Run tests with coverage report (fails under 80%)
	uv run pytest tests/unit --cov=src/cemaf --cov-fail-under=80 -q --no-header

lint:  ## Ruff check + Ruff format check
	uv run ruff check src/cemaf/
	uv run ruff format --check src/cemaf/

typecheck:  ## MyPy strict-typed check
	uv run mypy src/cemaf/

format:  ## Apply Ruff format in place (use before commit)
	uv run ruff format src/cemaf/

benchmark:  ## Run local benchmark + veracity checks
	uv run python benchmarks/run_benchmarks.py

benchmark-report:  ## Generate local JSON + Markdown benchmark evidence
	uv run python benchmarks/run_benchmarks.py \
		--json-out benchmarks/results/local-baseline.json \
		--markdown-out benchmarks/results/local-baseline.md

# ---- audits (the work surfaced over fires 1..N) ----------------------------

audit-links:  ## Verify every internal markdown link + anchor (83 .md files)
	uv run python docs/architecture/scripts/check_doc_links.py

audit-graph:  ## Verify the showcase's module-graph matches src/cemaf/ AST
	uv run python docs/architecture/build_graph_data.py --check

audit-traces:  ## Verify inlined showcase TRACE_DATA matches on-disk JSONs
	uv run python docs/architecture/scripts/produce_dag_trace.py --check

audit-all: audit-links audit-graph audit-traces  ## Run every audit (CI-equivalent)
	@echo "✓ all audits clean"

check: lint typecheck audit-all  ## Pre-PR: lint + typecheck + every audit
	@echo "✓ pre-PR check clean"

# ---- demo / traces / showcase ----------------------------------------------

demo:  ## Regenerate the 7 real CEMAF run traces (writes docs/architecture/traces/*.json)
	uv run python docs/architecture/scripts/produce_dag_trace.py

demo-step:  ## Regenerate one trace (use STEP=N, e.g. make demo-step STEP=7)
	@if [ -z "$(STEP)" ]; then echo "usage: make demo-step STEP=N (N is 1..7)"; exit 2; fi
	uv run python docs/architecture/scripts/produce_dag_trace.py --step $(STEP)

traces: demo  ## Alias for `make demo`

showcase:  ## Open the interactive demo (macOS / Linux open command)
	@if command -v open >/dev/null; then \
		open docs/architecture/cemaf-graph.html; \
	elif command -v xdg-open >/dev/null; then \
		xdg-open docs/architecture/cemaf-graph.html; \
	else \
		echo "open docs/architecture/cemaf-graph.html in your browser"; \
	fi

docs-search:  ## Search CEMAF's own docs (use Q="your question")
	@if [ -z "$(Q)" ]; then echo 'usage: make docs-search Q="composition root runtime services"'; exit 2; fi
	uv run cemaf docs search "$(Q)" -k 3

# ---- cleanup ---------------------------------------------------------------

clean:  ## Remove caches + build artifacts (keeps .venv)
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build *.egg-info
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} +
	@echo "✓ caches cleared"
