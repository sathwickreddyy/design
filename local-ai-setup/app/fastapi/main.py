# Standard Library
import logging
import os
from typing import Any, Dict, Optional

# Third Party
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check - verifies both FastAPI and Ollama connectivity."""
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


@app.get("/api/v1/models")
async def list_models() -> Dict[str, Any]:
    """List all models available in Ollama."""
    logger.info("Listing available models")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [
            {
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / 1e9, 1),
            }
            for m in data.get("models", [])
        ]
        logger.info(f"Found {len(models)} models")
        return {"models": models}
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=503, detail=str(e))
