# Publishing & Releases

This document describes the process for publishing CEMAF to PyPI and creating releases.

## Overview

CEMAF uses automated publishing via GitHub Actions with PyPI trusted publishing for security. No API tokens are stored in GitHub secrets.

## Publishing to PyPI

### Automated Publishing (Recommended)

The project uses GitHub Actions to automatically publish to PyPI when you create a GitHub release.

**Steps:**

1. **Update version in `pyproject.toml`**
   ```toml
   version = "0.2.0"  # Update this
   ```

2. **Update CHANGELOG.md**
   - Add new version section with changes
   - Follow [Keep a Changelog](https://keepachangelog.com/) format

3. **Commit and push changes**
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to 0.2.0"
   git push origin main
   ```

4. **Create a GitHub Release**
   - Go to: https://github.com/drchinca/cemaf/releases/new
   - Tag: `v0.2.0` (must start with `v`)
   - Title: `v0.2.0`
   - Description: Copy from CHANGELOG.md for this version
   - Click "Publish release"

5. **Automatic publishing**
   - GitHub Actions workflow triggers automatically
   - Builds package with `uv build`
   - Publishes to PyPI using trusted publishing
   - Package available at: https://pypi.org/project/cemaf/

**Monitor the workflow:**
- Go to: https://github.com/drchinca/cemaf/actions
- Check the "Publish to PyPI" workflow run
- Verify successful completion

### Manual Publishing (Fallback)

If GitHub Actions is unavailable, you can publish manually:

**Prerequisites:**
- PyPI account with API token
- `uv` installed

**Steps:**

1. **Set up PyPI token**
   ```bash
   # Option A: Environment variable
   export UV_PUBLISH_TOKEN="pypi-YOUR_TOKEN_HERE"

   # Option B: ~/.pypirc file
   cat > ~/.pypirc <<'EOF'
   [pypi]
   username = __token__
   password = pypi-YOUR_TOKEN_HERE
   EOF
   chmod 600 ~/.pypirc
   ```

2. **Build the package**
   ```bash
   uv build
   ```

3. **Publish to PyPI**
   ```bash
   uv publish
   ```

4. **Verify publication**
   ```bash
   pip index versions cemaf
   ```

## PyPI Trusted Publishing Setup

CEMAF uses PyPI's trusted publishing (OIDC) for secure, token-free publishing.

**Initial Setup (One-time):**

1. **Go to PyPI trusted publishers**
   - https://pypi.org/manage/account/publishing/

2. **Add a new pending publisher** (before first release)
   - PyPI Project Name: `cemaf`
   - Owner: `drchinca`
   - Repository name: `cemaf`
   - Workflow name: `publish-to-pypi.yml`
   - Environment name: `pypi`

3. **After first manual publish** (if needed)
   - Package must exist on PyPI first
   - Then configure as "trusted publisher" for the existing package

**Benefits:**
- No long-lived API tokens to manage
- Automatic token rotation
- More secure than static tokens
- No secrets stored in GitHub

## Version Numbering

CEMAF follows [Semantic Versioning](https://semver.org/):

- **MAJOR** version (1.0.0): Incompatible API changes
- **MINOR** version (0.1.0): New functionality, backwards compatible
- **PATCH** version (0.0.1): Bug fixes, backwards compatible

**Current Status:**
- Version: `0.1.0`
- Status: Alpha

**Version Progression:**
- Alpha: `0.1.x` → `0.2.x` (breaking changes allowed)
- Beta: `0.9.x` → `0.10.x` (API stabilizing)
- Stable: `1.0.0` (API stability guaranteed)

## Release Checklist

Before creating a release:

- [ ] All tests passing (`pytest tests/`)
- [ ] All pre-commit hooks passing
- [ ] Version bumped in `pyproject.toml`
- [ ] CHANGELOG.md updated with changes
- [ ] Documentation updated (if needed)
- [ ] README.md updated (if needed)
- [ ] No sensitive information in git history
- [ ] Branch is up-to-date with main

## GitHub Actions Workflow

The publishing workflow (`.github/workflows/publish-to-pypi.yml`) consists of:

**Jobs:**

1. **Build**
   - Checks out code
   - Sets up Python 3.14
   - Installs `uv`
   - Builds source distribution and wheel
   - Uploads artifacts

2. **Publish to PyPI** (on release)
   - Downloads build artifacts
   - Publishes to PyPI using trusted publishing
   - Environment: `pypi`

**Triggers:**
- `release: types: [published]` - Automatic on GitHub release
- `workflow_dispatch` - Manual trigger (build artifacts only, no publish)

## Troubleshooting

### Build fails

**Error**: Build fails during `uv build`

**Solution:**
1. Check `pyproject.toml` syntax
2. Verify all dependencies are specified
3. Run locally: `uv build` to debug

### Publish fails

**Error**: Authentication failure during publish

**Solution:**
1. Verify trusted publishing is configured on PyPI
2. Check workflow has `id-token: write` permission
3. Verify environment name matches (`pypi`)

### Version conflict

**Error**: "File already exists" on PyPI

**Solution:**
- PyPI doesn't allow overwriting versions
- Bump to next version in `pyproject.toml`
- Each release must have a unique version number

### Package not installable

**Error**: `pip install cemaf` fails

**Solution:**
1. Check Python version: CEMAF requires Python 3.14+
2. Verify package exists: `pip index versions cemaf`
3. Wait a few minutes for PyPI propagation
4. Check dependencies in `pyproject.toml`

## Resources

- **PyPI Package**: https://pypi.org/project/cemaf/
- **GitHub Releases**: https://github.com/drchinca/cemaf/releases
- **GitHub Actions**: https://github.com/drchinca/cemaf/actions
- **PyPI Trusted Publishing**: https://docs.pypi.org/trusted-publishers/
- **Semantic Versioning**: https://semver.org/
- **Keep a Changelog**: https://keepachangelog.com/

## Contact

For publishing questions or issues:
- **GitHub Issues**: https://github.com/drchinca/cemaf/issues
- **Discord**: https://discord.gg/C8ZXAbD8
- **Email**: chincadr@gmail.com
