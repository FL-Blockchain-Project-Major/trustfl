#!/usr/bin/env bash
# Bootstrap script for development environment

set -euo pipefail

echo "==> Initializing TrustFL developer workspace..."

if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo "Environment template created. Ready for dependency installation."
