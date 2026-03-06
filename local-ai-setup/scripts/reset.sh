#!/usr/bin/env zsh
# =============================================================================
# reset.sh - Nuclear reset: removes all containers, volumes, and downloaded models
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "============================================="
echo " WARNING: DESTRUCTIVE OPERATION"
echo "============================================="
echo ""
echo "This will:"
echo "  - Stop all Local AI containers"
echo "  - Remove Docker volumes (ollama-data, open-webui-data)"
echo "  - Delete ALL downloaded models (~100GB)"
echo "  - Delete Open WebUI settings and chat history"
echo ""
echo "Press Ctrl+C within 10 seconds to cancel..."
echo ""

for i in {10..1}; do
  printf "\r  Proceeding in %2d seconds..." "$i"
  sleep 1
done
echo ""

echo ""
echo "Stopping containers and removing volumes..."
docker compose down -v --remove-orphans

echo ""
echo "============================================="
echo " Reset complete."
echo "============================================="
echo ""
echo "To rebuild:"
echo "  make start"
echo "  make pull-models"
echo ""
