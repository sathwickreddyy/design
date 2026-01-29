"""
FastAPI application to demonstrate sticky sessions.
Returns the unique APP_NAME and current process ID.
"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Sticky Sessions Demo")

# Get APP_NAME from environment variable
APP_NAME = os.environ.get("APP_NAME", "unknown")
PROCESS_ID = os.getpid()


@app.get("/")
async def root(request: Request):
    """Root endpoint returning server identification."""
    return {
        "app_name": APP_NAME,
        "process_id": PROCESS_ID,
        "client_ip": request.client.host,
        "message": f"Hello from {APP_NAME}!"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "app_name": APP_NAME}


@app.get("/info")
async def info(request: Request):
    """Detailed info endpoint."""
    return {
        "app_name": APP_NAME,
        "process_id": PROCESS_ID,
        "client_ip": request.client.host,
        "headers": dict(request.headers),
        "explanation": {
            "sticky_sessions": "With ip_hash, your IP always routes to the same backend server",
            "without_sticky": "Without ip_hash, requests would round-robin across all servers"
        }
    }
