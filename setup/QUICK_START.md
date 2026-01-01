# Quick Start: Publishing to PyPI

## What You Need to Do

### 1. Create PyPI Accounts

- **TestPyPI**: https://test.pypi.org/account/register/
- **PyPI**: https://pypi.org/account/register/

### 2. Generate API Tokens

For each account (TestPyPI and PyPI):

1. Log in to your account
2. Go to **Account Settings** → **API tokens**
   - Direct link: https://pypi.org/manage/account/token/
   - TestPyPI: https://test.pypi.org/manage/account/token/
3. Click **Add API token**
4. Name it (e.g., "CEMAF Publishing")
5. Scope: **"Upload packages"**
6. Click **Add token**
7. **COPY THE TOKEN** - it starts with `pypi-` and you won't see it again!

Save both tokens securely:
- TestPyPI token: `pypi-...` (for testing)
- PyPI token: `pypi-...` (for production)

### 3. Install Build Tools

```bash
python -m pip install --upgrade setuptools wheel twine build
```

### 4. Build the Package

```bash
cd /path/to/cemaf
python -m build
```

This creates `dist/` folder with `.whl` and `.tar.gz` files.

### 5. Test on TestPyPI

```bash
python -m twine upload --repository testpypi dist/*
```

**When prompted:**
- Username: `__token__` (literally, with underscores)
- Password: Your TestPyPI API token

**Test installation:**
```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cemaf
```

### 6. Publish to PyPI

```bash
python -m twine upload dist/*
```

**When prompted:**
- Username: `__token__` (literally, with underscores)
- Password: Your PyPI API token (NOT TestPyPI token!)

### 7. Verify

```bash
pip install cemaf
python -c "import cemaf; print(cemaf.__version__)"
```

## Using the Script

Or use the provided script:

```bash
# Test upload
./setup/scripts/publish.sh test

# Production upload
./setup/scripts/publish.sh prod
```

## Important Notes

- **Username is always**: `__token__` (with underscores)
- **Password is your API token** (the `pypi-...` string)
- Use **TestPyPI token** for TestPyPI, **PyPI token** for PyPI
- Tokens don't expire but can be revoked
- If you lose a token, generate a new one (old one is automatically revoked)

## Troubleshooting

**"Invalid or non-existent authentication information"**
- Check username is exactly `__token__` (not `__token-` or `token__`)
- Verify token is correct (starts with `pypi-`)
- Make sure you're using the right token for the right repository

**"Filename or contents already exists"**
- Version already published - increment version in `pyproject.toml` and `src/cemaf/__init__.py`

For more details, see [PACKAGING.md](PACKAGING.md).
