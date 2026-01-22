import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shared.router import router
from shared.storage import MinIOStorage

app = FastAPI(
    title="Video Transcoding API",
    description="Upload videos and transcode them using Temporal workflows",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize MinIO buckets on startup
@app.on_event("startup")
async def startup_event():
    storage = MinIOStorage()
    print("✓ MinIO buckets initialized")
    print(f"✓ API Server ready at http://localhost:8000")
    print(f"✓ Temporal address: {os.getenv('TEMPORAL_ADDRESS', 'localhost:7233')}")

# Include video router
app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": "Video Transcoding API",
        "status": "running",
        "endpoints": {
            "upload": "/api/videos/upload",
            "status": "/api/videos/status/{video_id}",
            "download": "/api/videos/download/{video_id}",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
