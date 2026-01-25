"""
YouTube download activity.

Purpose: Download YouTube videos and upload to MinIO storage.
Consumers: Download workers polling 'download-queue'.
Logic:
  1. Validate YouTube URL
  2. Download video using yt-dlp (best quality up to 1080p)
  3. Upload to MinIO videos bucket
  4. Return video metadata for downstream processing
"""
import os
import logging
import tempfile
import yt_dlp
from temporalio import activity
from shared.storage import MinIOStorage

logger = logging.getLogger(__name__)


@activity.defn
async def download_youtube_video(video_id: str, youtube_url: str) -> dict:
    """
    Download a YouTube video and upload to MinIO.
    
    Args:
        video_id: Unique identifier for the video
        youtube_url: YouTube video URL
        
    Returns:
        Dictionary with:
        - video_id: Video identifier
        - title: YouTube video title
        - duration_seconds: Video duration
        - file_size_bytes: Uploaded file size
        
    Raises:
        Exception: If download fails or upload fails
    """
    logger.info(f"[{video_id}] Starting YouTube download: {youtube_url}")
    
    storage = MinIOStorage()
    
    try:
        # Create temp directory for download
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, f"{video_id}.mp4")
            
            # yt-dlp options - download best quality up to 1080p
            ydl_opts = {
                'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best',
                'outtmpl': output_path,
                'merge_output_format': 'mp4',
                'quiet': True,
                'no_warnings': True,
            }
            
            logger.info(f"[{video_id}] Downloading from YouTube...")
            
            # Download video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                video_title = info.get('title', 'Unknown')
                duration = info.get('duration', 0)
                
            logger.info(f"[{video_id}] Downloaded: {video_title} ({duration}s)")
            
            # Verify file exists
            if not os.path.exists(output_path):
                raise Exception("Downloaded file not found")
            
            # Read downloaded file
            with open(output_path, 'rb') as f:
                file_content = f.read()
            
            if len(file_content) == 0:
                raise Exception("Downloaded file is empty")
            
            file_size = len(file_content)
            logger.info(f"[{video_id}] File size: {file_size} bytes ({file_size / 1024 / 1024:.2f} MB)")
        
        # Upload to MinIO with .mp4 extension
        logger.info(f"[{video_id}] Uploading to MinIO...")
        from shared.storage import StoragePaths
        storage.upload_fileobj(
            file_data=file_content,
            bucket_name="videos",
            object_name=StoragePaths.source_video(video_id)
        )
        
        logger.info(f"[{video_id}] Upload complete")
        
        return {
            "video_id": video_id,
            "title": video_title,
            "duration_seconds": duration,
            "file_size_bytes": file_size,
        }
        
    except Exception as e:
        logger.error(f"[{video_id}] Download failed: {e}")
        raise Exception(f"Failed to download YouTube video: {str(e)}")
