"""
FastAPI router for video transcoding API endpoints.

Provides:
    - POST /upload: Upload video file directly
    - POST /upload-youtube-url: Download from YouTube and process
    - GET /status/{video_id}: Check workflow status
    - GET /download/{video_id}: Get pre-signed download URL
"""
import os
import uuid
import logging
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from shared.storage import MinIOStorage
from shared.workflows import VideoWorkflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Initialize MinIO storage
storage = MinIOStorage()

# Temporal client (will be initialized on first use)
temporal_client = None


async def get_temporal_client() -> Client:
    """
    Get or create Temporal client connection.
    
    Returns:
        Temporal Client instance
    """
    global temporal_client
    if temporal_client is None:
        temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
        temporal_client = await Client.connect(temporal_address)
    return temporal_client


class YouTubeUrlRequest(BaseModel):
    """Request model for YouTube URL upload."""
    url: str  # YouTube URL (youtube.com or youtu.be)


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Upload a video file and trigger the transcoding workflow.
    
    Args:
        file: Video file (multipart/form-data)
        
    Returns:
        - video_id: Unique identifier for the video
        - workflow_id: Temporal workflow ID
        - status: "processing"
    """
    logger.info(f"Upload video request received: {file.filename}")
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    try:
        # Generate unique video ID
        video_id = "video_" + str(uuid.uuid4())[:8]
        logger.info(f"Generated video_id: {video_id}")
        
        # Read file content
        file_content = await file.read()
        
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Empty file provided")
        
        logger.info(f"File size: {len(file_content)} bytes")
        
        # Upload to MinIO with .mp4 extension
        storage.upload_fileobj(
            file_data=file_content,
            bucket_name="videos",
            object_name=f"{video_id}.mp4"
        )

        logger.info(f"Video file uploaded to MinIO with video_id: {video_id}")
        
        # Start Temporal workflow (no YouTube URL, file already uploaded)
        client = await get_temporal_client()
        workflow_handle = await client.start_workflow(
            VideoWorkflow.run,
            args=[video_id, None],  # None for youtube_url since file is already in MinIO
            id=f"video-workflow-{video_id}",
            task_queue="video-tasks"
        )

        logger.info(f"Workflow started with ID: {workflow_handle.id}")
        
        return {
            "video_id": video_id,
            "workflow_id": workflow_handle.id,
            "status": "processing",
            "message": "Video uploaded successfully. Processing started."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-youtube-url")
async def upload_youtube_video(request: YouTubeUrlRequest):
    """
    Queue a YouTube video for download and processing.
    
    Args:
        url: YouTube URL (youtube.com/watch?v=xxx or youtu.be/xxx)
        
    Returns:
        - video_id: Unique identifier for the video
        - workflow_id: Temporal workflow ID
        - status: "queued" (download will happen asynchronously)
        - message: Status message
    """
    url = str(request.url).strip()
    logger.info(f"YouTube upload request received: {url}")
    
    # Validate YouTube URL
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(
            status_code=400, 
            detail="URL must be a YouTube URL (youtube.com or youtu.be)"
        )
    
    try:
        # Generate unique video ID
        video_id = "video_" + str(uuid.uuid4())[:8]
        logger.info(f"Generated video_id: {video_id} for URL: {url}")
        
        # Start Temporal workflow with YouTube URL
        # Download will happen asynchronously in download worker
        client = await get_temporal_client()
        workflow_handle = await client.start_workflow(
            VideoWorkflow.run,
            args=[video_id, url],  # Pass youtube_url as second argument
            id=f"video-workflow-{video_id}",
            task_queue="video-tasks",
        )
        
        logger.info(f"Workflow queued with ID: {workflow_handle.id}")
        
        return {
            "video_id": video_id,
            "workflow_id": workflow_handle.id,
            "status": "queued",
            "message": "YouTube video queued for download and processing",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error queuing YouTube video: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{video_id}")
async def get_video_status(video_id: str):
    """
    Get the status of a video processing workflow.
    
    Args:
        video_id: The video ID to check
        
    Returns:
        - video_id: The video ID
        - workflow_id: Temporal workflow ID
        - status: "processing" or "completed"
        - result: Workflow result (if completed)
    """
    # Validate video_id
    if not video_id or not video_id.startswith("video_"):
        raise HTTPException(
            status_code=400, 
            detail="Invalid video_id format"
        )
    
    try:
        client = await get_temporal_client()
        workflow_id = f"video-workflow-{video_id}"
        
        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)
        
        # Try to get result (non-blocking)
        try:
            result = await handle.result()
            return {
                "video_id": video_id,
                "workflow_id": workflow_id,
                "status": "completed",
                "result": result
            }
        except Exception:
            # Workflow still running or failed
            return {
                "video_id": video_id,
                "workflow_id": workflow_id,
                "status": "processing",
                "message": "Workflow is still running"
            }
            
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{video_id}")
async def download_video(video_id: str, resolution: str = "720p"):
    """
    Get pre-signed URL to download encoded video.
    
    Args:
        video_id: The video ID
        resolution: Resolution (default: 720p)
        
    Returns:
        - video_id: The video ID
        - resolution: Requested resolution
        - download_url: Pre-signed S3 URL (valid for 1 hour)
    """
    # Validate video_id
    if not video_id or not video_id.startswith("video_"):
        raise HTTPException(
            status_code=400, 
            detail="Invalid video_id format"
        )
    
    # Validate resolution
    valid_resolutions = ["720p", "480p", "1080p"]
    if resolution not in valid_resolutions:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid resolution. Must be one of: {valid_resolutions}"
        )
    
    try:
        object_name = f"{video_id}_{resolution}.mp4"
        
        # Check if file exists
        if not storage.file_exists("encoded", object_name):
            raise HTTPException(
                status_code=404, 
                detail="Encoded video not found. Processing may still be in progress."
            )
        
        # Generate pre-signed URL (valid for 1 hour)
        url = storage.s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': 'encoded',
                'Key': object_name
            },
            ExpiresIn=3600
        )
        
        return {
            "video_id": video_id,
            "resolution": resolution,
            "download_url": url,
            "expires_in": "1 hour"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating download URL: {e}")
        raise HTTPException(status_code=500, detail=str(e))
