# Packaging CEMAF for PyPI

This guide explains how to package and publish CEMAF to PyPI so it can be installed from anywhere using `pip install cemaf`.

## Prerequisites

1. **PyPI Accounts**: Create accounts on:
   - **TestPyPI** (for testing): https://test.pypi.org/account/register/
   - **PyPI** (production): https://pypi.org/account/register/

2. **Build Tools**: Install build and upload tools:
   ```bash
   python -m pip install --upgrade setuptools wheel twine build
   ```

3. **API Tokens**: Generate API tokens from PyPI/TestPyPI:
   - Log in to your PyPI/TestPyPI account
   - Go to **Account Settings** → **API tokens** (or visit https://pypi.org/manage/account/token/)
   - Click **Add API token**
   - Give it a name (e.g., "CEMAF Publishing")
   - Set scope to **"Upload packages"** (or "Entire account" for full access)
   - Click **Add token**
   - **IMPORTANT**: Copy the token immediately - it starts with `pypi-` and you won't see it again!
   - Save it securely (password manager, environment variable, etc.)

   **Note**: You need separate tokens for TestPyPI and PyPI. Generate both.

   **Usage**: When uploading, use:
   - Username: `__token__` (literally, with underscores)
   - Password: Your API token (the `pypi-...` string)

## Project Structure

CEMAF uses the modern `pyproject.toml` format. The package structure is:

```
cemaf/
├── pyproject.toml          # Package configuration
├── README.md               # Package description
├── LICENSE                 # MIT License
├── src/
│   └── cemaf/             # Main package
│       ├── __init__.py
│       └── ...            # All modules
├── tests/                 # Test suite
├── docs/                  # Documentation
└── examples/              # Example code
```

## Step 1: Update Version

Before each release, update the version in:
- `pyproject.toml`: `version = "0.1.0"`
- `src/cemaf/__init__.py`: `__version__ = "0.1.0"`

Use [Semantic Versioning](https://semver.org/):
- **MAJOR.MINOR.PATCH** (e.g., 0.1.0 → 0.1.1 for bug fixes, 0.2.0 for new features)

## Step 2: Update URLs (Important!)

Edit `pyproject.toml` and update the `urls` section with your actual repository:

```toml
urls = {
    "Homepage" = "https://github.com/yourusername/cemaf",
    "Documentation" = "https://github.com/yourusername/cemaf/docs",
    "Repository" = "https://github.com/yourusername/cemaf",
    "Issues" = "https://github.com/yourusername/cemaf/issues",
}
```

## Step 3: Build Distribution Packages

Build both wheel and source distribution:

```bash
cd /Users/bado/iccha/iccha_context_multi_agent/cemaf
python -m build
```

This creates:
- `dist/cemaf-0.1.0-py3-none-any.whl` (wheel - preferred)
- `dist/cemaf-0.1.0.tar.gz` (source distribution)

## Step 4: Test on TestPyPI (Recommended)

Always test on TestPyPI first to ensure everything works:

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*
```

When prompted:
- **Username**: `__token__` (literally, with underscores)
- **Password**: Your TestPyPI API token (starts with `pypi-...`)

After successful upload, test installation:

```bash
# Install from TestPyPI to verify
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cemaf

# Or test in a fresh environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cemaf
python -c "import cemaf; print(cemaf.__version__)"
```

**Note**: The `--extra-index-url` is needed because TestPyPI packages may have dependencies that aren't on TestPyPI.

## Step 5: Publish to PyPI

Once tested successfully, publish to production PyPI:

```bash
python -m twine upload dist/*
```

When prompted:
- **Username**: `__token__` (literally, with underscores)
- **Password**: Your PyPI API token (starts with `pypi-...`)

**Important**: Use your **production PyPI** token, not the TestPyPI token!

## Step 6: Verify Installation

After publishing, verify it works:

```bash
# Create a fresh virtual environment
python -m venv test_env
source test_env/bin/activate  # On Windows: test_env\Scripts\activate

# Install from PyPI
pip install cemaf

# Test import
python -c "import cemaf; print(cemaf.__version__)"
```

## Installation Options

Users can install CEMAF with different options:

```bash
# Minimal installation (core only)
pip install cemaf

# With specific optional dependencies
pip install "cemaf[tiktoken]"
pip install "cemaf[openai]"
pip install "cemaf[anthropic]"

# With all optional dependencies
pip install "cemaf[all]"

# Development installation (from source)
pip install -e ".[dev]"
```

## Updating the Package

For subsequent releases:

1. **Update version** in `pyproject.toml` and `__init__.py`
2. **Update CHANGELOG.md** (if you have one)
3. **Build**: `python -m build`
4. **Test**: Upload to TestPyPI first
5. **Publish**: `python -m twine upload dist/*`

## Troubleshooting

### "Package already exists"
- Version already published. Increment version number.

### "Invalid distribution"
- Check `pyproject.toml` syntax
- Ensure all required fields are present
- Verify package structure

### "Authentication failed"
- **Username must be exactly**: `__token__` (with underscores, not hyphens)
- Check API token is correct (starts with `pypi-`)
- Ensure token has "Upload packages" scope
- Make sure you're using the right token (TestPyPI token for TestPyPI, PyPI token for PyPI)
- Token may have been revoked - generate a new one if needed
- Check that token hasn't expired (tokens don't expire, but can be revoked)

### "Package not found after upload"
- PyPI indexing takes a few minutes
- Wait 5-10 minutes, then try installing

## Automated Publishing (GitHub Actions)

You can automate publishing with GitHub Actions. Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [created]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.14'
      - name: Install build tools
        run: pip install build twine
      - name: Build package
        run: python -m build
      - name: Publish to PyPI
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
        run: python -m twine upload dist/*
```

Then:
1. Add `PYPI_API_TOKEN` to GitHub Secrets
2. Create a GitHub Release to trigger publishing

## Package Metadata

The `pyproject.toml` includes:
- **Name**: `cemaf`
- **Version**: Semantic versioning
- **Description**: Package description
- **Dependencies**: Core dependencies (pydantic, typing-extensions)
- **Optional Dependencies**: Grouped by feature (tiktoken, openai, anthropic, etc.)
- **Classifiers**: Python versions, topics, license
- **URLs**: Homepage, documentation, repository

## Best Practices

1. **Always test on TestPyPI first**
2. **Use semantic versioning**
3. **Keep dependencies minimal** (core deps only)
4. **Document optional dependencies** clearly
5. **Update README** with installation instructions
6. **Tag releases** in git: `git tag v0.1.0 && git push --tags`

## Quick Reference

```bash
# Build
python -m build

# Test upload
python -m twine upload --repository testpypi dist/*

# Production upload
python -m twine upload dist/*

# Install from PyPI
pip install cemaf

# Install with extras
pip install "cemaf[all]"
```

## Next Steps

After publishing:
1. Update README with installation instructions
2. Add badges to README (PyPI version, downloads)
3. Create GitHub Release with changelog
4. Announce on social media / forums
