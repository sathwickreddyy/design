# Standard Library
import logging
import os
from typing import Any, Dict, Optional

# Third Party
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Local/Application
from routers.chat import router as chat_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("local-ai-fastapi")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Local AI Assistant API",
    description="Thin FastAPI wrapper over local Ollama for custom agent workflows.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])


@app.get(
    "/health",
    summary="Health check",
    responses={
        200: {
            "description": "All systems healthy",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "ollama": "connected",
                        "ollama_url": "http://ollama:11434",
                        "models_available": 12,
                    }
                }
            },
        },
        503: {"description": "Ollama service unavailable"},
    },
)
async def health() -> Dict[str, Any]:
    """
    Health check endpoint.
    
    Verifies that both FastAPI and Ollama are running and connected.
    Returns the Ollama URL and count of available models.
    
    Use this to confirm your local AI stack is ready before making requests.
    """
    logger.info("Health check requested")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            model_count = len(resp.json().get("models", []))
        logger.info(f"Health check passed. Ollama has {model_count} models.")
        return {
            "status": "healthy",
            "ollama": "connected",
            "ollama_url": OLLAMA_BASE_URL,
            "models_available": model_count,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Ollama unreachable: {e}")


class ModelInfo(BaseModel):
    """Information about an available model."""

    name: str = Field(..., description="Full model name (e.g., phi3:3.8b)")
    size_gb: float = Field(..., description="Disk size in gigabytes")


class ModelsListResponse(BaseModel):
    """Response containing list of available models."""

    count: int = Field(..., description="Number of available models")
    models: list[ModelInfo] = Field(..., description="List of model details")


@app.get(
    "/api/v1/models",
    response_model=ModelsListResponse,
    summary="List available models",
    responses={
        200: {
            "description": "Successfully retrieved model list",
            "content": {
                "application/json": {
                    "example": {
                        "count": 3,
                        "models": [
                            {"name": "phi3:3.8b", "size_gb": 2.2},
                            {"name": "neural-chat:7b", "size_gb": 4.0},
                            {"name": "deepseek-r1:8b", "size_gb": 4.9},
                        ],
                    }
                }
            },
        },
        503: {"description": "Ollama service unavailable"},
    },
)
async def list_models() -> ModelsListResponse:
    """
    List all available models.
    
    Retrieves the complete list of LLM models currently installed in Ollama,
    including their disk sizes.
    
    **Model categories:**
    - **Speed tier (3-8B):** phi3, neural-chat, llama3.1, deepseek-r1:8b — 8-20s per response
    - **Mid tier (12-14B):** phi4, gemma3:12b, deepseek-r1:14b — 15-30s per response
    - **Premium tier (27-32B):** qwen2.5, deepseek-r1:32b, gemma3, qwen-coder — 30-50s per response
    - **Embeddings:** nomic-embed-text — for RAG and vector search, not for chat
    
    Use this to see what models you have available before making chat requests.
    """
    logger.info("Listing available models")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [
            ModelInfo(
                name=m["name"],
                size_gb=round(m.get("size", 0) / 1e9, 1),
            )
            for m in data.get("models", [])
        ]
        logger.info(f"Found {len(models)} models")
        return ModelsListResponse(count=len(models), models=models)
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=503, detail=str(e))
