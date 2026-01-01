# Setup Directory

This directory contains setup, deployment, and packaging files for the CEMAF project.

## Structure

```
setup/
├── scripts/              # Deployment and utility scripts
│   ├── publish.sh   # PyPI publishing script
│   ├── benchmark.py # Benchmarking utilities
│   └── profile.py   # Profiling utilities
├── PACKAGING.md     # Complete packaging guide for PyPI
├── QUICK_START.md   # Quick reference for publishing
└── README.md        # This file
```

## Scripts

### Publishing

**Quick Start**: See [QUICK_START.md](QUICK_START.md) for step-by-step instructions.

**Using the script**:
```bash
# From project root
./setup/scripts/publish.sh test   # Upload to TestPyPI
./setup/scripts/publish.sh prod   # Upload to PyPI
```

**Manual publishing**:
```bash
# Build
python -m build

# Test on TestPyPI
python -m twine upload --repository testpypi dist/*
# Username: __token__
# Password: Your TestPyPI API token

# Publish to PyPI
python -m twine upload dist/*
# Username: __token__
# Password: Your PyPI API token
```

**Important**:
- Username is always `__token__` (with underscores)
- Password is your API token (starts with `pypi-`)
- Generate tokens at: https://pypi.org/manage/account/token/

### Benchmarking

```bash
python setup/scripts/benchmark.py
```

### Profiling

```bash
python setup/scripts/profile.py
```
