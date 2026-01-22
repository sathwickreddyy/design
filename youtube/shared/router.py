import os
import uuid
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from temporalio.client import Client
from shared.storage import MinIOStorage
from shared.workflows import VideoWorkflow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Initialize MinIO storage
storage = MinIOStorage()

# Temporal client (will be initialized in app startup)
temporal_client = None


async def get_temporal_client():
    """Get or create Temporal client"""
    global temporal_client
    if temporal_client is None:
        temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
        temporal_client = await Client.connect(temporal_address)
    return temporal_client


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """
    Upload a video file and trigger the transcoding workflow
    
    Returns:
        - video_id: Unique identifier for the video
        - workflow_id: Temporal workflow ID
        - status: "processing"
    """
    logger.info(f"Upload video request received: {file.filename}")
    try:
        # Generate unique video ID
        video_id = "video_" + str(uuid.uuid4())[:8]
        logger.info(f"Generated video_id: {video_id}")
        
        # Read file content
        file_content = await file.read()
        
        # Upload to MinIO
        storage.upload_fileobj(
            file_data=file_content,
            bucket_name="videos",
            object_name=video_id
        )

        logger.info(f"Video file uploaded to MinIO with video_id: {video_id}")
        logger.info("Starting Temporal workflow for video processing...")
        # Start Temporal workflow
        client = await get_temporal_client()
        workflow_handle = await client.start_workflow(
            VideoWorkflow.run,
            video_id,
            id=f"video-workflow-{video_id}",
            task_queue="video-tasks"
        )

        logger.info(f"Workflow started with ID: {workflow_handle.id}")
        
        return {
            "video_id": video_id,
            "workflow_id": workflow_handle.id,
            "status": "processing",
            "message": f"Video uploaded successfully. Processing started."
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{video_id}")
async def get_video_status(video_id: str):
    """
    Get the status of a video processing workflow
    """
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
            # Workflow still running
            return {
                "video_id": video_id,
                "workflow_id": workflow_id,
                "status": "processing",
                "message": "Workflow is still running"
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{video_id}")
async def download_video(video_id: str, resolution: str = "720p"):
    """
    Get pre-signed URL to download encoded video
    
    Args:
        video_id: The video ID
        resolution: Resolution (default: 720p)
    """
    try:
        object_name = f"{video_id}_{resolution}"
        
        # Check if file exists
        if not storage.file_exists("encoded", object_name):
            raise HTTPException(
                status_code=404, 
                detail=f"Encoded video not found. Processing may still be in progress."
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
        raise HTTPException(status_code=500, detail=str(e))
