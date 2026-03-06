# Local AI Assistant Stack

A production-grade, fully offline local AI assistant running on **Mac mini M4 Pro (48GB)**. Uses Ollama for model inference, Open WebUI for chat, and an optional FastAPI wrapper for custom agent workflows.

**After the initial Docker image pulls and model downloads, this stack runs 100% offline. No cloud, no API keys, no telemetry.**

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Model Selection](#model-selection)
- [Model Comparison Table](#model-comparison-table)
- [When to Use Which Model](#when-to-use-which-model)
- [Disk Usage](#disk-usage)
- [Memory Behavior on 48GB Mac](#memory-behavior-on-48gb-mac)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Managing Models](#managing-models)
- [FastAPI Wrapper (Optional)](#fastapi-wrapper-optional)
- [Project Structure](#project-structure)
- [Exposed Ports](#exposed-ports)
- [Troubleshooting](#troubleshooting)
- [Splunk Log Queries](#splunk-log-queries)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Docker (observability-net)                │
│                                                              │
│  ┌────────────┐    ┌─────────────┐    ┌────────────────────┐ │
│  │  Ollama    │◄───│ Open WebUI  │    │ FastAPI (optional) │ │
│  │  :11434    │    │  :3000      │    │  :8100             │ │
│  │            │◄───│             │    │                    │ │
│  │ Models:    │    └─────────────┘    └────────────────────┘ │
│  │ deepseek   │                                              │
│  │ qwen2.5    │    ┌─────────────┐                           │
│  │ qwen-coder │◄───│model-puller │ (init, runs once)         │
│  │ gemma3     │    └─────────────┘                           │
│  │ nomic-emb  │                                              │
│  └────────────┘                                              │
│       │                    │                                 │
│  [ollama-data]      [open-webui-data]                        │
│  (Docker volume)    (Docker volume)                          │
└──────────────────────────────────────────────────────────────┘
```

---

## Model Selection

### Why These Models?

| Model | Why Selected |
|-------|-------------|
| **deepseek-r1:32b** | Best-in-class chain-of-thought reasoning at this parameter count. Excels at analytical questions, step-by-step problem solving, and complex debugging. |
| **qwen2.5-coder:32b** | Top-tier code generation model. Handles Python, Go, TypeScript, code review, refactoring, and implementation planning. |
| **qwen2.5:32b** | Strong general assistant with 32K context, multilingual support, and structured output (JSON/YAML). Ideal for system design discussions. |
| **gemma3:27b** | Google's premium multimodal model. Supports image understanding. Strong alternative general assistant. |
| **nomic-embed-text** | Lightweight embedding model for future RAG/vector search workflows. Not for direct chat. |

### What Was Excluded and Why

| Excluded | Reason |
|----------|--------|
| 70B models | Won't fit in 48GB — even quantized, a 70B model uses 35-40GB leaving nothing for the OS. |
| 7B/8B models | Too small for the quality bar needed for system design and production code work. |
| Cloud-dependent models | This stack is designed to be fully offline. |

---

## Model Comparison Table

| Model | Parameters | Disk Size | RAM When Loaded | Context | Quantization | Role |
|-------|-----------|-----------|----------------|---------|-------------|------|
| deepseek-r1:32b | 32B | ~20 GB | ~20 GB | 32K | Q4_K_M | Reasoning |
| qwen2.5-coder:32b | 32B | ~20 GB | ~20 GB | 32K | Q4_K_M | Coding |
| qwen2.5:32b | 32B | ~20 GB | ~20 GB | 32K | Q4_K_M | General |
| gemma3:27b | 27B | ~17 GB | ~17 GB | 8K | Q4_K_M | Multimodal |
| nomic-embed-text | 137M | ~0.3 GB | ~0.3 GB | 8K | FP16 | Embeddings |
| **Total on disk** | | **~77 GB** | | | | |

---

## When to Use Which Model

### `qwen2.5:32b` — General Assistant (Default)
- System design discussions and architecture tradeoffs
- Long technical Q&A and structured explanations
- Document summarization and analysis
- Generating structured output (JSON, YAML, markdown tables)
- Multilingual tasks
- **When in doubt, start here.**

### `deepseek-r1:32b` — Deep Reasoning
- Complex debugging thought processes
- Analytical questions requiring step-by-step reasoning
- Mathematical and logical problem solving
- Root cause analysis
- Architecture decision evaluation with explicit tradeoffs
- **Use when you need the model to "show its work."**

### `qwen2.5-coder:32b` — Code Expert
- Code generation (Python, Go, TypeScript, SQL, etc.)
- Implementation planning and task breakdown
- Code review and refactoring
- Backend design (FastAPI, Django, databases, APIs)
- Writing and fixing tests
- **Use for anything that produces or analyzes code.**

### `gemma3:27b` — Multimodal & Alternative
- Image understanding (upload screenshots, diagrams, whiteboard photos)
- Multimodal tasks combining text and images
- Alternative general assistant when you want a second opinion
- Creative writing and brainstorming

### `nomic-embed-text` — Embeddings Only
- Document embeddings for RAG pipelines
- Semantic search and similarity
- **Not for chat. Used programmatically via API.**

---

## Disk Usage

| Item | Size |
|------|------|
| Ollama models (all 5) | ~77 GB |
| Docker images (Ollama + Open WebUI) | ~5 GB |
| Open WebUI data volume | < 1 GB |
| **Total** | **~83 GB** |

You'll stay well within your 100 GB budget.

---

## Memory Behavior on 48GB Mac

This is the most important section to understand.

### How It Works

1. **Models live on disk, not in RAM.** All 5 models (~77 GB total) are stored on the Docker volume. They do NOT all consume RAM simultaneously.

2. **Only the active model is loaded into RAM.** When you select `qwen2.5:32b` in Open WebUI, Ollama loads ~20 GB into unified memory (shared CPU/GPU on Apple Silicon).

3. **`OLLAMA_MAX_LOADED_MODELS=1`** ensures only one large model occupies memory at any time. If you switch from `qwen2.5:32b` to `deepseek-r1:32b`, Ollama unloads the first and loads the second.

4. **`OLLAMA_KEEP_ALIVE=10m`** automatically unloads an idle model after 10 minutes, freeing memory for other work (VS Code, Docker, browsers, etc.).

5. **Model loading takes 10-30 seconds** depending on the model size and SSD speed. This is the "cold start" cost when switching models.

### Memory Budget

```
48 GB Total Unified Memory
├── macOS + system services     ~6 GB
├── Docker Desktop overhead     ~2 GB
├── Open WebUI                  ~0.5 GB
├── Active Ollama model         ~17-20 GB
├── Metal GPU context           ~2-4 GB
└── Free for VS Code, browser   ~16-21 GB
```

This leaves plenty of headroom for normal development work while running a 32B model.

---

## Prerequisites

1. **Docker Desktop for Mac** installed and running
2. **At least 100 GB free disk space** (for models + Docker images)
3. **Docker Desktop memory:** Go to Docker Desktop → Settings → Resources → set RAM to at least **36 GB** (recommended: **40 GB**)
4. **`curl`** available in terminal (pre-installed on macOS)

---

## Quick Start

### 1. Create the Docker network (one-time)

```bash
make create-network
```

### 2. Start the stack

```bash
make start
```

This starts Ollama and Open WebUI. Ollama will be ready when the health check passes.

### 3. Pull all models (first time only, takes a while)

```bash
make pull-models
```

This downloads ~77 GB of model weights. Go grab a coffee. On a 100 Mbps connection, expect 1-2 hours.

**After this completes, you never need internet again.**

### 4. Open the chat UI

Open [http://localhost:3000](http://localhost:3000) in your browser.

1. Create an admin account on first launch
2. Select a model from the dropdown at the top
3. Start chatting

### 5. Verify everything is working

```bash
make status
```

Or test Ollama directly:

```bash
# List models
curl http://localhost:11434/api/tags | python3 -m json.tool

# Quick test
curl http://localhost:11434/api/generate -d '{
  "model": "qwen2.5:32b",
  "prompt": "What is consistent hashing?",
  "stream": false
}' | python3 -m json.tool
```

---

## Usage

### Starting and Stopping

```bash
make start        # Start Ollama + Open WebUI
make stop         # Stop all services (preserves data)
make restart      # Restart everything
make status       # Health check all services
```

### Using Shell Scripts Directly

```bash
./scripts/start.sh
./scripts/stop.sh
./scripts/pull-models.sh
./scripts/status.sh
./scripts/reset.sh        # DANGER: deletes all models and data
```

### Switching Models in Open WebUI

1. Open [http://localhost:3000](http://localhost:3000)
2. Click the model dropdown at the top of the chat
3. Select a different model
4. Wait 10-30 seconds for the new model to load
5. The previous model is automatically unloaded from memory

### Logs

```bash
make logs          # Tail all service logs
make logs-ollama   # Tail Ollama logs only
make logs-webui    # Tail Open WebUI logs only
```

---

## Managing Models

### Add a New Model

```bash
# Pull any model from the Ollama library
docker exec ollama ollama pull <model-name>

# Example: add Phi-3
docker exec ollama ollama pull phi3:14b
```

The model will appear in the Open WebUI dropdown automatically.

### Remove a Model

```bash
# Remove a specific model
docker exec ollama ollama rm <model-name>

# Example: remove gemma3
docker exec ollama ollama rm gemma3:27b
```

### List Installed Models

```bash
docker exec ollama ollama list
```

### Check What's Currently Loaded in RAM

```bash
docker exec ollama ollama ps
```

---

## FastAPI Wrapper (Optional)

A thin API layer for building custom agent workflows, tool calling, or programmatic access.

### Start It

```bash
make fastapi-up
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (verifies Ollama connectivity) |
| `/api/v1/models` | GET | List available models |
| `/api/v1/chat` | POST | Send a prompt and get a response |
| `/docs` | GET | Interactive Swagger UI |

### Example Request

```bash
curl -X POST http://localhost:8100/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:32b",
    "prompt": "Explain the CAP theorem in 3 sentences.",
    "temperature": 0.3
  }'
```

### Stop It

```bash
make fastapi-down
```

---

## Project Structure

```
local-ai-setup/
├── .env                          # Environment configuration
├── .gitignore                    # Git ignore rules
├── docker-compose.yml            # Service definitions
├── Makefile                      # Developer shortcuts
├── README.md                     # This file
├── scripts/
│   ├── start.sh                  # Start the stack
│   ├── stop.sh                   # Stop the stack
│   ├── pull-models.sh            # Pull all models (idempotent)
│   ├── status.sh                 # Health check
│   └── reset.sh                  # Nuclear reset (deletes everything)
├── app/
│   ├── fastapi/                  # Optional FastAPI wrapper
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── routers/
│   │       ├── __init__.py
│   │       └── chat.py
│   ├── config/
│   │   └── models.yaml           # Model registry with roles
│   ├── prompts/                  # System prompts for different use cases
│   │   ├── system_design.txt
│   │   ├── coding.txt
│   │   ├── reasoning.txt
│   │   └── general.txt
│   └── data/                     # Future: document ingestion for RAG
│       └── .gitkeep
└── .github/
    ├── copilot-instructions.md
    ├── docker-standards.md
    ├── python-standards.md
    └── splunk-debugging.md
```

---

## Exposed Ports

| Port | Service | URL |
|------|---------|-----|
| 11434 | Ollama API | http://localhost:11434 |
| 3000 | Open WebUI | http://localhost:3000 |
| 8100 | FastAPI (optional) | http://localhost:8100 |

---

## Troubleshooting

### Ollama won't start

```bash
# Check Docker Desktop is running
docker info

# Check container logs
docker logs ollama

# Verify port isn't already in use
lsof -i :11434
```

### Models won't pull

```bash
# Check Ollama is healthy
curl http://localhost:11434/api/tags

# Check disk space
df -h

# Pull manually
docker exec ollama ollama pull qwen2.5:32b
```

### Open WebUI can't connect to Ollama

The most common issue is networking. Both services must be on the `observability-net` network.

```bash
# Verify both containers are on the same network
docker network inspect observability-net | grep -A2 "ollama\|open-webui"

# Check if Ollama is reachable from Open WebUI
docker exec open-webui curl -sf http://ollama:11434/api/tags
```

### Out of memory / system slowdown

```bash
# Check what model is loaded
docker exec ollama ollama ps

# Manually unload all models
curl http://localhost:11434/api/generate -d '{"model": "qwen2.5:32b", "keep_alive": 0}'

# Reduce Docker Desktop memory allocation (Settings → Resources)
# Minimum recommended: 36 GB for this stack
```

### Model loads slowly

- **First load after pulling:** 15-30 seconds is normal for a 32B model
- **Subsequent loads (within keep_alive):** Near instant
- **After idle timeout (10 min):** Full reload required
- **SSD speed matters:** M4 Pro's SSD is fast enough, but if Docker Desktop allocated storage is fragmented, restart Docker.

### Docker Desktop issues on macOS

| Issue | Fix |
|-------|-----|
| Docker won't start | Restart Docker Desktop. If persistent, delete `~/Library/Containers/com.docker.docker` |
| High memory usage | Reduce Docker Desktop memory in Settings → Resources |
| Slow I/O | Enable VirtioFS in Settings → General → File sharing |
| Port already in use | `lsof -i :PORT` then kill the process or change the port in `.env` |
| Network not found | Run `make create-network` |
| Volumes filling disk | `docker system df` to check, `docker system prune` to clean |

### Complete reset

If everything is broken, nuclear option:

```bash
make reset
# Then rebuild:
make start
make pull-models
```

---

## Splunk Log Queries

If you have Splunk monitoring connected to your Docker environment, use these queries to verify the stack:

### Check Ollama Activity

```spl
index=main sourcetype="docker:json" source="*ollama*"
| spath input=log
| table _time, log
| sort -_time
```

### Check Model Load Events

```spl
index=main sourcetype="docker:json" source="*ollama*" "loading model"
| spath input=log
| table _time, log
| sort -_time
```

### Check Open WebUI Errors

```spl
index=main sourcetype="docker:json" source="*open-webui*" "error" OR "ERROR"
| spath input=log
| table _time, log
| sort -_time
```

### Check FastAPI Requests

```spl
index=main sourcetype="docker:json" source="*local-ai-fastapi*" "Chat request"
| spath input=log
| table _time, log
| sort -_time
```

---

## Offline Guarantee

After running `make pull-models` once:

- **No internet required** for any operation
- **No API keys** needed
- **No telemetry** — all analytics are disabled
- **No external calls** — Open WebUI talks only to local Ollama
- **All data stays on your machine** — models, conversations, embeddings

You own your data. You own your compute. Everything runs locally.
