#!/bin/bash

# Exit on error
set -e

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Setting up development environment..."

export PATH="$HOME/.local/bin:$PATH"

cd "$PROJECT_ROOT"

if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Installing project dependencies..."
uv sync

echo "Development environment setup complete!"
echo "Use: uv run capgains ...  or  uv run pytest tests/"
