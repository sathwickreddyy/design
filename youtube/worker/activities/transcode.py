"""
Transcoding activities for video processing.

Purpose: CPU-heavy video transcoding using ffmpeg to multiple resolutions.
Consumers: Transcode workers polling 'transcode-queue'.
Logic:
  1. Download original video from MinIO
  2. Run ffmpeg to transcode to target resolution
  3. Upload encoded video to MinIO 'encoded' bucket
  4. Cleanup temp files
"""
import os
import subprocess
import tempfile
from pathlib import Path
from temporalio import activity
from shared.storage import MinIOStorage


# Resolution configurations: height -> (scale_filter, name)
RESOLUTION_CONFIG = {
    320: {"scale": "scale=-2:320", "name": "320p", "target": "568x320"},
    480: {"scale": "scale=-2:480", "name": "480p", "target": "854x480"},
    720: {"scale": "scale=-2:720", "name": "720p", "target": "1280x720"},
    1080: {"scale": "scale=-2:1080", "name": "1080p", "target": "1920x1080"},
}


async def _transcode_to_resolution(metadata: dict, target_height: int) -> dict:
    """
    Generic transcode function for any resolution.
    
    Args:
        metadata: Metadata dict with 'video_id', 'width', 'height'
        target_height: Target resolution height (320, 480, 720, 1080)
        
    Returns:
        Dictionary with transcoding results
        
    Raises:
        RuntimeError: If transcoding fails
    """
    video_id = metadata.get("video_id")
    original_width = metadata.get("width")
    original_height = metadata.get("height")
    
    config = RESOLUTION_CONFIG[target_height]
    resolution_name = config["name"]
    
    activity.logger.info(
        f"[{video_id}] Starting {resolution_name} transcode "
        f"(original: {original_width}x{original_height})"
    )
    
    storage = MinIOStorage()
    temp_input_path = None
    temp_output_path = None
    
    try:
        # Step 1: Download original video from MinIO
        activity.logger.info(f"[{video_id}] Downloading original video")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_in:
            temp_input_path = tmp_in.name
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=f"{video_id}.mp4",
            file_path=temp_input_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download video {video_id} from MinIO")
        
        # Step 2: Prepare output file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{resolution_name}.mp4") as tmp_out:
            temp_output_path = tmp_out.name
        
        # Step 3: Build ffmpeg command
        cmd = [
            "ffmpeg",
            "-i", temp_input_path,
            "-vf", config["scale"],
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            "-y",
            temp_output_path
        ]
        
        activity.logger.info(f"[{video_id}] Running ffmpeg for {resolution_name}")
        
        # Step 4: Execute ffmpeg
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        progress_lines = []
        for line in process.stderr:
            if line.startswith('frame=') or line.startswith('time='):
                progress_lines.append(line.strip())
                if len(progress_lines) % 100 == 0:
                    activity.logger.info(f"[{video_id}] {resolution_name} progress: {progress_lines[-1]}")
        
        process.wait(timeout=600)
        
        if process.returncode != 0:
            stderr_output = '\n'.join(progress_lines[-20:])
            raise RuntimeError(f"ffmpeg failed for {resolution_name}: {stderr_output}")
        
        activity.logger.info(f"[{video_id}] ffmpeg {resolution_name} complete")
        
        # Step 5: Upload transcoded video
        encoded_video_id = f"{video_id}_{resolution_name}.mp4"
        
        activity.logger.info(f"[{video_id}] Uploading {resolution_name} to encoded/{encoded_video_id}")
        upload_success = storage.upload_file(
            file_path=temp_output_path,
            bucket_name="encoded",
            object_name=encoded_video_id
        )
        
        if not upload_success:
            raise RuntimeError(f"Failed to upload {resolution_name} video to MinIO")
        
        # Step 6: Calculate stats
        output_size = os.path.getsize(temp_output_path)
        input_size = os.path.getsize(temp_input_path)
        compression_ratio = (1 - output_size / input_size) * 100
        
        result_data = {
            "video_id": video_id,
            "resolution": resolution_name,
            "original_resolution": f"{original_width}x{original_height}",
            "target_resolution": config["target"],
            "encoded_video_id": encoded_video_id,
            "success": True,
            "input_file_size": input_size,
            "output_file_size": output_size,
            "compression_ratio": f"{compression_ratio:.1f}%"
        }
        
        activity.logger.info(
            f"[{video_id}] {resolution_name} complete: "
            f"{input_size / (1024*1024):.1f}MB -> {output_size / (1024*1024):.1f}MB "
            f"({compression_ratio:.1f}% change)"
        )
        
        return result_data
        
    except subprocess.TimeoutExpired:
        activity.logger.error(f"[{video_id}] ffmpeg timeout for {resolution_name}")
        raise RuntimeError(f"ffmpeg execution timed out for {resolution_name}")
    except Exception as e:
        activity.logger.error(f"[{video_id}] Error transcoding to {resolution_name}: {e}")
        raise
    finally:
        # Cleanup
        if temp_input_path and Path(temp_input_path).exists():
            Path(temp_input_path).unlink()
        if temp_output_path and Path(temp_output_path).exists():
            Path(temp_output_path).unlink()


@activity.defn
async def transcode_to_320p(metadata: dict) -> dict:
    """Transcode video to 320p resolution."""
    return await _transcode_to_resolution(metadata, 320)


@activity.defn
async def transcode_to_480p(metadata: dict) -> dict:
    """Transcode video to 480p resolution."""
    return await _transcode_to_resolution(metadata, 480)


@activity.defn
async def transcode_to_720p(metadata: dict) -> dict:
    """Transcode video to 720p resolution."""
    return await _transcode_to_resolution(metadata, 720)


@activity.defn
async def transcode_to_1080p(metadata: dict) -> dict:
    """Transcode video to 1080p resolution."""
    return await _transcode_to_resolution(metadata, 1080)
