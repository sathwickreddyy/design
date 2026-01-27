"""
Thumbnail generation activity for video processing.

Purpose: Extract frames from videos to create thumbnails.
Consumers: Workers polling 'thumbnail-queue'.
Logic:
  - Auto: Extract frame at 00:00:05 (or 00:00:01 for short videos)
  - Custom: Extract frame at user-specified timestamp
  - Scene-based: Use FFmpeg thumbnail filter to find "interesting" frame
  - Upload: Custom image provided by user
"""
import os
import re
import tempfile
import subprocess
import threading
import queue as thread_queue
from pathlib import Path
from typing import Optional, Literal
from temporalio import activity
from shared.storage import MinIOStorage, StoragePaths


# Thumbnail configuration
THUMBNAIL_CONFIG = {
    "default_timestamp": "00:00:05",
    "fallback_timestamp": "00:00:01",
    "min_video_duration": 5.0,  # seconds
    "output_format": "jpg",
    "quality": 2,  # FFmpeg quality (2-31, lower is better)
}


def run_ffmpeg_streaming(cmd: list, timeout: int = 60) -> tuple[int, str]:
    """
    Run FFmpeg with streaming stderr to prevent memory issues.
    
    Uses a circular buffer to capture only the last N lines of stderr,
    preventing memory exhaustion on long-running operations.
    
    Args:
        cmd: FFmpeg command as list
        timeout: Maximum execution time in seconds
        
    Returns:
        Tuple of (return_code, last_stderr_output)
    """
    stderr_buffer = thread_queue.Queue(maxsize=100)
    
    def stream_stderr(pipe, q):
        try:
            for line in iter(pipe.readline, ''):
                if q.full():
                    try:
                        q.get_nowait()
                    except thread_queue.Empty:
                        pass
                q.put(line)
        finally:
            pipe.close()
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True
    )
    
    thread = threading.Thread(target=stream_stderr, args=(process.stderr, stderr_buffer))
    thread.daemon = True
    thread.start()
    
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        return -1, "Process timed out"
    
    thread.join(timeout=1)
    
    # Collect last lines for error reporting
    collected = []
    while not stderr_buffer.empty():
        try:
            collected.append(stderr_buffer.get_nowait())
        except thread_queue.Empty:
            break
    
    return return_code, "".join(collected[-30:])


def parse_timestamp(timestamp: str) -> float:
    """
    Parse timestamp string to seconds.
    
    Supports formats:
        - "00:00:05" (HH:MM:SS)
        - "00:05" (MM:SS)
        - "5" or "5.0" (seconds)
    
    Returns:
        Timestamp in seconds
    """
    if ":" in timestamp:
        parts = timestamp.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
    return float(timestamp)


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


@activity.defn
async def generate_thumbnail(
    video_id: str,
    mode: Literal["auto", "custom", "scene_based"] = "auto",
    custom_timestamp: Optional[str] = None,
    video_duration: Optional[float] = None
) -> dict:
    """
    Generate a thumbnail for a video.
    
    Purpose: Create preview image for video display.
    Consumers: Workflow orchestrator after metadata extraction.
    
    Modes:
        - auto: Extract frame at 00:00:05 (or 00:00:01 for short videos)
        - custom: Extract frame at user-specified timestamp
        - scene_based: Use FFmpeg thumbnail filter to find visually interesting frame
    
    Args:
        video_id: Unique identifier for the video
        mode: Thumbnail generation mode
        custom_timestamp: User-specified timestamp (for "custom" mode)
        video_duration: Video duration in seconds (helps pick timestamp)
        
    Returns:
        Dictionary with:
        - video_id: str
        - thumbnail_key: str (path in MinIO)
        - timestamp: str (when frame was extracted)
        - mode: str
        - success: bool
        - error: str | None (if partial failure)
    """
    activity.logger.info(f"[{video_id}] Generating thumbnail (mode={mode})")
    
    storage = MinIOStorage()
    temp_input_path = None
    temp_output_path = None
    
    try:
        # Step 1: Download source video
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_in:
            temp_input_path = tmp_in.name
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=StoragePaths.source_video(video_id),
            file_path=temp_input_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download video {video_id} from MinIO")
        
        # Step 2: Determine timestamp
        if mode == "custom" and custom_timestamp:
            timestamp = custom_timestamp
            # Validate timestamp doesn't exceed duration
            if video_duration:
                ts_seconds = parse_timestamp(timestamp)
                if ts_seconds >= video_duration:
                    # Clamp to 1 second before end
                    timestamp = format_timestamp(max(0, video_duration - 1))
                    activity.logger.warning(
                        f"[{video_id}] Custom timestamp exceeded duration, clamped to {timestamp}"
                    )
        elif video_duration and video_duration < THUMBNAIL_CONFIG["min_video_duration"]:
            timestamp = THUMBNAIL_CONFIG["fallback_timestamp"]
            activity.logger.info(f"[{video_id}] Short video, using fallback timestamp {timestamp}")
        else:
            timestamp = THUMBNAIL_CONFIG["default_timestamp"]
        
        # Step 3: Generate thumbnail
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_out:
            temp_output_path = tmp_out.name
        
        if mode == "scene_based":
            # Use FFmpeg thumbnail filter to find interesting frame
            # Analyzes 100 frames and picks the most visually complex one
            cmd = [
                "ffmpeg",
                "-i", temp_input_path,
                "-vf", "thumbnail=n=100,scale=1280:720:force_original_aspect_ratio=decrease",
                "-vframes", "1",
                "-q:v", str(THUMBNAIL_CONFIG["quality"]),
                "-y",
                temp_output_path
            ]
            used_timestamp = "scene_based"
        else:
            # Standard frame extraction at specific timestamp
            cmd = [
                "ffmpeg",
                "-ss", timestamp,  # Seek before input (fast)
                "-i", temp_input_path,
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease",
                "-vframes", "1",
                "-q:v", str(THUMBNAIL_CONFIG["quality"]),
                "-y",
                temp_output_path
            ]
            used_timestamp = timestamp
        
        activity.logger.info(f"[{video_id}] Running FFmpeg thumbnail extraction")
        return_code, stderr = run_ffmpeg_streaming(cmd, timeout=60)
        
        if return_code != 0:
            activity.logger.error(f"[{video_id}] FFmpeg failed: {stderr[-500:]}")
            raise RuntimeError(f"FFmpeg thumbnail extraction failed: {stderr[-200:]}")
        
        # Verify output exists and has content
        if not Path(temp_output_path).exists():
            raise RuntimeError("Thumbnail file was not created")
        
        output_size = Path(temp_output_path).stat().st_size
        if output_size == 0:
            raise RuntimeError("Thumbnail file is empty")
        
        # Step 4: Upload to MinIO thumbnails bucket
        thumbnail_key = StoragePaths.thumbnail(video_id)
        
        # Ensure thumbnails bucket exists
        storage.ensure_buckets(["thumbnails"])
        
        upload_success = storage.upload_file(
            file_path=temp_output_path,
            bucket_name="thumbnails",
            object_name=thumbnail_key
        )
        
        if not upload_success:
            raise RuntimeError("Failed to upload thumbnail to MinIO")
        
        activity.logger.info(
            f"[{video_id}] Thumbnail generated: thumbnails/{thumbnail_key} "
            f"({output_size / 1024:.1f} KB, timestamp={used_timestamp})"
        )
        
        return {
            "video_id": video_id,
            "thumbnail_key": thumbnail_key,
            "thumbnail_bucket": "thumbnails",
            "timestamp": used_timestamp,
            "mode": mode,
            "size_bytes": output_size,
            "success": True,
            "error": None
        }
        
    except Exception as e:
        activity.logger.error(f"[{video_id}] Thumbnail generation failed: {e}")
        return {
            "video_id": video_id,
            "thumbnail_key": None,
            "timestamp": None,
            "mode": mode,
            "success": False,
            "error": str(e)
        }
        
    finally:
        # Cleanup temp files
        if temp_input_path and Path(temp_input_path).exists():
            Path(temp_input_path).unlink()
        if temp_output_path and Path(temp_output_path).exists():
            Path(temp_output_path).unlink()


@activity.defn
async def upload_custom_thumbnail(
    video_id: str,
    source_bucket: str,
    source_key: str
) -> dict:
    """
    Copy a user-uploaded custom thumbnail to the thumbnails bucket.
    
    Purpose: Allow users to provide their own thumbnail image.
    Consumers: Workflow orchestrator when custom image is provided.
    
    Args:
        video_id: Unique identifier for the video
        source_bucket: Bucket containing the uploaded image
        source_key: Key of the uploaded image
        
    Returns:
        Dictionary with thumbnail info
    """
    activity.logger.info(f"[{video_id}] Copying custom thumbnail from {source_bucket}/{source_key}")
    
    storage = MinIOStorage()
    temp_path = None
    
    try:
        # Download from source
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            temp_path = tmp.name
        
        success = storage.download_file(
            bucket_name=source_bucket,
            object_name=source_key,
            file_path=temp_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download custom thumbnail from {source_bucket}/{source_key}")
        
        # Upload to thumbnails bucket
        thumbnail_key = StoragePaths.thumbnail(video_id)
        storage.ensure_buckets(["thumbnails"])
        
        upload_success = storage.upload_file(
            file_path=temp_path,
            bucket_name="thumbnails",
            object_name=thumbnail_key
        )
        
        if not upload_success:
            raise RuntimeError("Failed to upload custom thumbnail")
        
        output_size = Path(temp_path).stat().st_size
        
        activity.logger.info(f"[{video_id}] Custom thumbnail uploaded: thumbnails/{thumbnail_key}")
        
        return {
            "video_id": video_id,
            "thumbnail_key": thumbnail_key,
            "thumbnail_bucket": "thumbnails",
            "mode": "custom_upload",
            "size_bytes": output_size,
            "success": True,
            "error": None
        }
        
    except Exception as e:
        activity.logger.error(f"[{video_id}] Custom thumbnail upload failed: {e}")
        return {
            "video_id": video_id,
            "thumbnail_key": None,
            "mode": "custom_upload",
            "success": False,
            "error": str(e)
        }
        
    finally:
        if temp_path and Path(temp_path).exists():
            Path(temp_path).unlink()


__all__ = ["generate_thumbnail", "upload_custom_thumbnail"]
