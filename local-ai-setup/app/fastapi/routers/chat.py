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

# Default system prompt to enforce English responses
DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant. 
Always respond in English, unless explicitly asked to use another language.
Be clear, concise, and helpful."""

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
router = APIRouter()


class ChatRequest(BaseModel):
    """Request schema for the chat endpoint."""

    model: str = Field(
        default="phi3:3.8b",
        description="Ollama model name to use for generation.",
        examples=["phi3:3.8b", "neural-chat:7b", "deepseek-r1:8b", "qwen2.5:32b"],
    )
    prompt: str = Field(
        ...,
        description="User prompt to send to the model.",
        examples=["What is machine learning?", "Explain REST APIs"],
    )
    system: Optional[str] = Field(
        default=DEFAULT_SYSTEM_PROMPT,
        description="System prompt to guide model behavior. If not provided, uses default English-enforcing prompt.",
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

    model: str = Field(..., description="Model used for generation")
    response: str = Field(..., description="Generated response text")
    total_duration_ms: Optional[float] = Field(
        None, description="Time taken for inference in milliseconds"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Chat with a local LLM model",
    description="Send a prompt to a local Ollama model and get a response. "
    "Non-streaming endpoint for simple request/response workflows.",
    responses={
        200: {
            "description": "Successful response",
            "content": {
                "application/json": {
                    "example": {
                        "model": "phi3:3.8b",
                        "response": "Machine learning is a branch of artificial intelligence...",
                        "total_duration_ms": 8234.5,
                    }
                }
            },
        },
        503: {"description": "Ollama service unavailable or model not found"},
    },
)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Chat with a local LLM model.

    Send a prompt to a local Ollama model and receive a response.
    This endpoint enforces English responses by default via the system prompt.
    Non-streaming endpoint for simple request/response workflows.

    **Model Selection Guide:**

    - **phi3:3.8b** (Speed tier): Ultra-fast 8-10s responses. Best for quick Q&A, brainstorming, quick lookups.
    - **neural-chat:7b** (Speed tier): Fast 10-15s conversational responses. Friendly, engaging. Best for chat.
    - **deepseek-r1:8b** (Balanced): 15-20s with reasoning capabilities. Best for problem solving.
    - **qwen2.5:32b** (Premium): 30-50s high-quality responses. Best for serious work, system design.

    **Examples:**
    - Quick question: Use `phi3:3.8b` with `temperature=0.3`
    - Creative writing: Use `neural-chat:7b` with `temperature=1.0`
    - Technical reasoning: Use `deepseek-r1:8b` with `temperature=0.5`
    - Production decision: Use `qwen2.5:32b` with `temperature=0.3`

    **System Prompt:**
    If you don't provide a system prompt, the default enforces English responses.
    You can override with a custom system prompt in the request.
    """
    logger.info(
        f"Chat request: model={request.model}, "
        f"prompt_length={len(request.prompt)}, "
        f"temperature={request.temperature}"
    )

    # Use default system prompt if not provided
    system_prompt = request.system or DEFAULT_SYSTEM_PROMPT

    payload: Dict[str, Any] = {
        "model": request.model,
        "prompt": request.prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": request.temperature,
        },
    }

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
