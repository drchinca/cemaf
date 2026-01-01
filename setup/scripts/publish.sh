#!/bin/bash
# CEMAF Publishing Script
# Usage: ./setup/scripts/publish.sh [test|prod]
# Run from project root: cd /path/to/cemaf && ./setup/scripts/publish.sh

set -e

MODE=${1:-test}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"

echo "🚀 CEMAF Publishing Script"
echo "=========================="
echo "Project root: $PROJECT_ROOT"
echo ""

# Check if build tools are installed
if ! python -m build --help &> /dev/null; then
    echo "❌ Build tools not installed. Installing..."
    pip install build twine
fi

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf dist/ build/ *.egg-info

# Build package
echo "📦 Building package..."
python -m build

# Check which mode
if [ "$MODE" = "test" ]; then
    echo "🧪 Uploading to TestPyPI..."
    echo ""
    echo "⚠️  When prompted:"
    echo "   Username: __token__"
    echo "   Password: Your TestPyPI API token (starts with pypi-...)"
    echo ""
    python -m twine upload --repository testpypi dist/*
    echo ""
    echo "✅ Uploaded to TestPyPI!"
    echo "📥 Test installation with:"
    echo "   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ cemaf"
elif [ "$MODE" = "prod" ]; then
    echo "⚠️  Uploading to PRODUCTION PyPI..."
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "❌ Cancelled"
        exit 1
    fi
    echo ""
    echo "⚠️  When prompted:"
    echo "   Username: __token__"
    echo "   Password: Your PyPI API token (starts with pypi-...)"
    echo ""
    python -m twine upload dist/*
    echo ""
    echo "✅ Uploaded to PyPI!"
    echo "📥 Install with: pip install cemaf"
else
    echo "❌ Invalid mode. Use 'test' or 'prod'"
    exit 1
fi

echo ""
echo "✨ Done!"
