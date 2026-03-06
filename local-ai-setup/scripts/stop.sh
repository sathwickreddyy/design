#!/usr/bin/env zsh
# =============================================================================
# stop.sh - Stop the Local AI Assistant stack
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "============================================="
echo " Local AI Assistant - Stopping"
echo "============================================="

docker compose down

echo ""
echo "All services stopped."
echo "Models and data are preserved in Docker volumes."
echo "Run './scripts/start.sh' to restart."
