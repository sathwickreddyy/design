# =============================================================================
# Local AI Assistant Stack - Makefile
# Mac mini M4 Pro | 48GB Unified Memory | Offline-First
# =============================================================================

.PHONY: help create-network start stop restart status pull-models reset logs \
        logs-ollama logs-webui clean fastapi-up fastapi-down

SHELL := /bin/zsh
COMPOSE := docker compose

# Default target
help: ## Show this help
	@echo ""
	@echo "Local AI Assistant Stack"
	@echo "========================"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
create-network: ## Create the external Docker network (run once)
	@docker network inspect observability-net >/dev/null 2>&1 || \
		(docker network create observability-net && \
		echo "Created network: observability-net") || \
		echo "Network observability-net already exists"

# ---------------------------------------------------------------------------
# Core Lifecycle
# ---------------------------------------------------------------------------
start: create-network ## Start Ollama + Open WebUI
	@echo "Starting Local AI stack..."
	$(COMPOSE) up -d ollama open-webui
	@echo ""
	@echo "Stack is starting. Run 'make status' to check health."
	@echo "Open WebUI: http://localhost:3000"

stop: ## Stop all services
	$(COMPOSE) down

restart: stop start ## Restart the stack

# ---------------------------------------------------------------------------
# Model Management
# ---------------------------------------------------------------------------
pull-models: create-network ## Pull all configured models into Ollama
	@echo "Starting model pull (this takes a while on first run)..."
	$(COMPOSE) up model-puller

# ---------------------------------------------------------------------------
# Status & Logs
# ---------------------------------------------------------------------------
status: ## Show service status and health
	@echo ""
	@echo "=== Container Status ==="
	$(COMPOSE) ps
	@echo ""
	@echo "=== Ollama Health ==="
	@curl -sf http://localhost:11434/api/tags 2>/dev/null | \
		python3 -c "import sys,json; data=json.load(sys.stdin); [print(f\"  {m['name']:30s} {m.get('size',0)/1e9:.1f}GB\") for m in data.get('models',[])]" 2>/dev/null || \
		echo "  Ollama is not responding yet."
	@echo ""

logs: ## Tail logs for all services
	$(COMPOSE) logs -f --tail=50

logs-ollama: ## Tail Ollama logs
	$(COMPOSE) logs -f --tail=100 ollama

logs-webui: ## Tail Open WebUI logs
	$(COMPOSE) logs -f --tail=100 open-webui

# ---------------------------------------------------------------------------
# FastAPI (Optional)
# ---------------------------------------------------------------------------
fastapi-up: create-network ## Start the optional FastAPI wrapper
	$(COMPOSE) --profile fastapi up -d fastapi
	@echo "FastAPI available at: http://localhost:8100"
	@echo "API docs at: http://localhost:8100/docs"

fastapi-down: ## Stop the FastAPI wrapper
	$(COMPOSE) --profile fastapi stop fastapi

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean: ## Stop and remove containers (keeps volumes/models)
	$(COMPOSE) down --remove-orphans

reset: ## Nuclear option: remove containers AND volumes (re-downloads models)
	@echo "WARNING: This will delete all models and Open WebUI data!"
	@echo "Press Ctrl+C within 5 seconds to cancel..."
	@sleep 5
	$(COMPOSE) down -v --remove-orphans
	@echo "Reset complete. Run 'make start && make pull-models' to rebuild."
