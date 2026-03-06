# Standard Library
import logging
import os
from typing import Any, Dict, Optional

# Third Party
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("local-ai-fastapi.chat")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
router = APIRouter()


class ChatRequest(BaseModel):
    """Request schema for the chat endpoint."""

    model: str = Field(
        default="qwen2.5:32b",
        description="Ollama model name to use for generation.",
    )
    prompt: str = Field(
        ...,
        description="User prompt to send to the model.",
    )
    system: Optional[str] = Field(
        default=None,
        description="Optional system prompt to guide model behavior.",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0.0 = deterministic, 2.0 = creative).",
    )
    stream: bool = Field(
        default=False,
        description="Whether to stream the response (not supported in this endpoint).",
    )


class ChatResponse(BaseModel):
    """Response schema for the chat endpoint."""

    model: str
    response: str
    total_duration_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Send a prompt to a local Ollama model and return the response.

    This is a non-streaming endpoint for simple request/response workflows.
    For streaming, use Open WebUI or the Ollama API directly.
    """
    logger.info(
        f"Chat request: model={request.model}, "
        f"prompt_length={len(request.prompt)}, "
        f"temperature={request.temperature}"
    )

    payload: Dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "stream": False,
        "options": {
            "temperature": request.temperature,
        },
    }

    if request.system:
        payload["system"] = request.system

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            logger.info(f"Sending request to Ollama: {OLLAMA_BASE_URL}/api/generate")
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        logger.error(f"Ollama request timed out for model {request.model}")
        raise HTTPException(
            status_code=504,
            detail="Model inference timed out. Large models may need more time.",
        )
    except Exception as e:
        logger.error(f"Ollama request failed: {e}")
        raise HTTPException(status_code=503, detail=f"Ollama error: {e}")

    response_text = data.get("response", "")
    total_duration = data.get("total_duration", 0) / 1e6  # nanoseconds to ms

    logger.info(
        f"Chat response: model={request.model}, "
        f"response_length={len(response_text)}, "
        f"duration_ms={total_duration:.0f}"
    )

    return ChatResponse(
        model=request.model,
        response=response_text,
        total_duration_ms=round(total_duration, 1),
    )
