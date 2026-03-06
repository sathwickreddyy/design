#!/usr/bin/env zsh
# =============================================================================
# status.sh - Check health and status of all services
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "============================================="
echo " Local AI Assistant - Status"
echo "============================================="

echo ""
echo "--- Container Status ---"
docker compose ps 2>/dev/null || echo "No containers running."

echo ""
echo "--- Ollama Health ---"
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "Ollama: HEALTHY"
  echo ""
  echo "Loaded models:"
  curl -sf http://localhost:11434/api/tags | \
    python3 -c "
import sys, json
data = json.load(sys.stdin)
models = data.get('models', [])
if not models:
    print('  No models installed yet.')
else:
    for m in models:
        size_gb = m.get('size', 0) / 1e9
        print(f'  {m[\"name\"]:40s} {size_gb:.1f} GB')
" 2>/dev/null
else
  echo "Ollama: NOT RESPONDING"
fi

echo ""
echo "--- Open WebUI Health ---"
if curl -sf http://localhost:3000 > /dev/null 2>&1; then
  echo "Open WebUI: HEALTHY (http://localhost:3000)"
else
  echo "Open WebUI: NOT RESPONDING"
fi

echo ""
echo "--- FastAPI Health (Optional) ---"
if curl -sf http://localhost:8100/health > /dev/null 2>&1; then
  echo "FastAPI: HEALTHY (http://localhost:8100)"
else
  echo "FastAPI: NOT RUNNING (start with 'make fastapi-up')"
fi

echo ""
echo "--- Docker Volumes ---"
docker volume ls --filter name=ollama-data --filter name=open-webui-data 2>/dev/null

echo ""
echo "--- System Memory ---"
echo "Docker Desktop memory usage:"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || echo "  No containers running."
echo ""
