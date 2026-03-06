#!/usr/bin/env zsh
# =============================================================================
# pull-models.sh - Pull all configured models into Ollama
# Idempotent: safe to re-run; skips already-downloaded models.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

MODELS=(
  "deepseek-r1:32b"
  "qwen2.5-coder:32b"
  "qwen2.5:32b"
  "gemma3:27b"
  "nomic-embed-text"
)

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

echo "============================================="
echo " Model Puller"
echo " Target: $OLLAMA_URL"
echo "============================================="

# Wait for Ollama to be ready
echo "Waiting for Ollama..."
until curl -sf "$OLLAMA_URL/api/tags" > /dev/null 2>&1; do
  printf "."
  sleep 3
done
echo " Ollama is ready."

TOTAL=${#MODELS[@]}
CURRENT=0

for model in "${MODELS[@]}"; do
  CURRENT=$((CURRENT + 1))
  echo ""
  echo "---------------------------------------------"
  echo " [$CURRENT/$TOTAL] Pulling: $model"
  echo "---------------------------------------------"

  # Check if model already exists
  if curl -sf "$OLLAMA_URL/api/tags" | grep -q "\"$model\""; then
    echo " Already installed, skipping."
    continue
  fi

  docker exec ollama ollama pull "$model"
  echo " Done: $model"
done

echo ""
echo "============================================="
echo " All models pulled."
echo "============================================="
echo ""
echo "Installed models:"
curl -sf "$OLLAMA_URL/api/tags" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for m in data.get('models', []):
    size_gb = m.get('size', 0) / 1e9
    print(f'  {m[\"name\"]:40s} {size_gb:.1f} GB')
" 2>/dev/null || echo "  (Could not list models)"
