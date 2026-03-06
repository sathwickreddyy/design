#!/usr/bin/env zsh
# =============================================================================
# start.sh - Start the Local AI Assistant stack
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "============================================="
echo " Local AI Assistant - Starting"
echo "============================================="

# Ensure external network exists
docker network inspect observability-net >/dev/null 2>&1 || \
  docker network create observability-net

echo "Starting Ollama and Open WebUI..."
docker compose up -d ollama open-webui

echo ""
echo "Waiting for Ollama to become healthy..."
until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do
  printf "."
  sleep 2
done
echo " Ready!"

echo ""
echo "============================================="
echo " Stack is running"
echo "============================================="
echo " Ollama API:   http://localhost:11434"
echo " Open WebUI:   http://localhost:3000"
echo ""
echo " Run './scripts/pull-models.sh' if models"
echo " have not been downloaded yet."
echo "============================================="
