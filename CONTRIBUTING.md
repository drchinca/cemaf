# Contributing to CEMAF

Thank you for considering contributing to CEMAF (Context Engineering Multi-Agent Framework)!

## Development Setup

1. Fork the repository
2. Clone your fork:

   ```bash
   git clone https://github.com/YOUR_USERNAME/cemaf.git
   cd cemaf
   ```

3. Install uv (if not already installed):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

4. Create virtual environment and install dependencies:

   ```bash
   uv venv
   uv sync
   ```

5. Install pre-commit hooks:
   ```bash
   uv run pre-commit install
   uv run pre-commit install --hook-type pre-push
   ```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b <gitusername>/your-feature-name
# or
git checkout -b <gitusername>/your-bug-fix
```

**Note**: Branch names must always follow the format `<gitusername>/*` where `<gitusername>` is your GitHub username.

### 2. Make Your Changes

- Write clear, concise code
- Follow the existing code style
- Add type hints to all functions
- Write docstrings for public functions
- CEMAF is async-first - use async/await where applicable

### 3. Write Tests

All new features must include tests. CEMAF has comprehensive test coverage with 1000+ tests across 50+ test files.

```python
import pytest

@pytest.mark.asyncio
async def test_your_feature():
    """Test description."""
    # Arrange
    input_data = setup_test_data()

    # Act
    result = await your_async_function(input_data)

    # Assert
    assert result == expected_value
```

### 4. Run Quality Checks

Before committing, ensure all checks pass:

```bash
# Run all tests with coverage
uv run pytest tests/ --cov=cemaf --cov-report=term-missing

# Run linting
uv run ruff check src tests

# Run formatting check
uv run ruff format --check src tests

# Run type checking
uv run mypy src

# Run security scan
uv run bandit -r src -c pyproject.toml
```

### 5. Commit Your Changes

Pre-commit hooks will run automatically:

```bash
git add .
git commit -m "feat: add new feature"
```

### Commit Message Format

Follow conventional commits:

- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `test:` Test changes
- `refactor:` Code refactoring
- `chore:` Build/tooling changes

### 6. Push and Create PR

```bash
git push origin <gitusername>/your-feature-name
```

Then create a Pull Request on GitHub.

## Code Style

### Python Style

- Line length: 110 characters
- Use type hints (enforced by mypy --strict)
- Follow PEP 8 (enforced by Ruff)
- Use descriptive variable names
- All code must be async-first where applicable

### Example

```python
async def calculate_total(items: list[dict[str, float]]) -> float:
    """Calculate the total price of items.

    Args:
        items: List of items with 'price' key

    Returns:
        Total price of all items

    Raises:
        ValueError: If items list is empty
    """
    if not items:
        raise ValueError("Items list cannot be empty")

    return sum(item["price"] for item in items)
```

## Testing Guidelines

### Test Coverage

- Aim for 90%+ coverage
- Test edge cases
- Test error conditions
- Use fixtures for common setup (see `tests/conftest.py`)

### Running Tests

```bash
# All tests with coverage
uv run pytest tests/ --cov=cemaf --cov-report=term-missing --cov-report=html

# Unit tests only
uv run pytest tests/unit/

# Integration tests
uv run pytest tests/integration/

# Specific test file
uv run pytest tests/unit/test_dag.py

# Specific test function
uv run pytest tests/unit/test_dag.py::test_node_creation

# Skip slow tests
uv run pytest tests/ -m "not slow"

# With verbose output
uv run pytest -v

# Stop on first failure
uv run pytest -x
```

### Test Markers

CEMAF uses custom pytest markers:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.slow` - Slow-running tests
- `@pytest.mark.llm` - Tests that involve LLM calls

## Performance Profiling

CEMAF includes profiling tools to help identify performance bottlenecks:

### Benchmarking

```bash
# Run all benchmarks
uv run python setup/scripts/benchmark.py

# Save baseline
uv run python setup/scripts/benchmark.py --save baseline

# Compare against baseline
uv run python setup/scripts/benchmark.py --compare baseline

# List saved benchmarks
uv run python setup/scripts/benchmark.py --list
```

### Profiling

```bash
# Profile function execution time
uv run python setup/scripts/profile.py cemaf.orchestration.executor.DAGExecutor.run

# Profile memory usage
uv run python setup/scripts/profile.py --memory cemaf.context.compiler.ContextCompiler.compile

# Line-by-line profiling
uv run python setup/scripts/profile.py --line-by-line cemaf.agents.base.Agent.run
```

## Documentation

### Docstrings

Use Google-style docstrings:

```python
async def function(arg1: str, arg2: int) -> bool:
    """Short description.

    Longer description if needed.

    Args:
        arg1: Description of arg1
        arg2: Description of arg2

    Returns:
        Description of return value

    Raises:
        ValueError: When something goes wrong
    """
```

## Framework Architecture

CEMAF is a modular, protocol-based framework. Key principles:

- **Protocol-based**: Use protocols for extensibility, not inheritance
- **Async-first**: All I/O operations are async
- **Type-safe**: Strict type checking with mypy
- **Minimal dependencies**: Core framework has minimal deps
- **Optional integrations**: LLM providers and vector stores are optional

### Key Modules

- `agents/` - Agent implementations and protocols
- `context/` - Context management and compilation
- `orchestration/` - DAG execution and task orchestration
- `tools/` - Tool protocols and implementations
- `llm/` - LLM client protocols
- `retrieval/` - Vector store and retrieval protocols
- `memory/` - Memory management
- `config/` - Configuration loading

## Questions?

Feel free to open an issue for:

- Bug reports
- Feature requests
- Questions about the codebase
- Architecture discussions

## License

By contributing to CEMAF, you agree that your contributions will be licensed under the [MIT License](LICENSE). This means:

- You retain copyright to your contributions
- Your contributions will be made available under the same MIT License as the rest of the project
- You grant the project maintainers and users the rights to use, modify, and distribute your contributions

For full details, see the [LICENSE](LICENSE) file in the repository root.
