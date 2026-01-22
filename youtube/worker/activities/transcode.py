"""
Transcoding activities for video processing
CPU-heavy, slow operations for video transcoding using ffmpeg
"""
import os
import subprocess
import tempfile
from pathlib import Path
from temporalio import activity
from shared.storage import MinIOStorage


@activity.defn
async def transcode_to_720p(metadata: dict) -> dict:
    """
    Transcode video to 720p resolution using ffmpeg
    
    Args:
        metadata: Metadata dictionary from extract_metadata activity
                  Must contain 'video_id', 'width', 'height'
    
    Returns:
        Dictionary with transcoding results:
        {
            "video_id": str,
            "original_resolution": "1920x1080",
            "target_resolution": "1280x720",
            "encoded_video_id": str,  # Object name in 'encoded' bucket
            "success": bool,
            "output_file_size": int    # Size in bytes
        }
    """
    video_id = metadata.get("video_id")
    original_width = metadata.get("width")
    original_height = metadata.get("height")
    
    activity.logger.info(
        f"Starting 720p transcode for video {video_id} "
        f"(original: {original_width}x{original_height})"
    )
    
    storage = MinIOStorage()
    temp_input_path = None
    temp_output_path = None
    
    try:
        # Step 1: Download original video from MinIO
        activity.logger.info(f"Downloading original video {video_id}")
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
        with tempfile.NamedTemporaryFile(delete=False, suffix="_720p.mp4") as tmp_out:
            temp_output_path = tmp_out.name
        
        # Step 3: Build ffmpeg command for 720p transcoding
        cmd = [
            "ffmpeg",
            "-i", temp_input_path,           # Input file
            "-vf", "scale=-2:720",            # Scale to 720p height, auto-calculate width
                                              # -2 ensures width is divisible by 2
            "-c:v", "libx264",                # Video codec: H.264
            "-preset", "medium",              # Encoding speed (medium = balanced)
            "-crf", "23",                     # Quality (18=visually lossless, 23=default, 28=lower quality)
            "-c:a", "aac",                    # Audio codec: AAC
            "-b:a", "128k",                   # Audio bitrate: 128 kbps
            "-movflags", "+faststart",        # Optimize for web streaming
            "-progress", "pipe:1",            # Send progress to stdout
            "-y",                             # Overwrite output file
            temp_output_path
        ]
        
        activity.logger.info(f"Running ffmpeg transcode: {' '.join(cmd)}")
        
        # Step 4: Execute ffmpeg with streaming output (avoid OOM on large files)
        # Use Popen to stream stderr line by line instead of capturing all in memory
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Stream progress lines and log periodically
        progress_lines = []
        for line in process.stderr:
            if line.startswith('frame=') or line.startswith('time='):
                progress_lines.append(line.strip())
                # Log every 100 lines to avoid flooding logs
                if len(progress_lines) % 100 == 0:
                    activity.logger.info(f"Progress: {progress_lines[-1]}")
        
        process.wait(timeout=600)  # 10 minutes timeout
        
        if process.returncode != 0:
            # Read stderr for error message
            stderr_output = '\n'.join(progress_lines[-20:])  # Last 20 lines
            raise RuntimeError(f"ffmpeg failed: {stderr_output}")
        
        # Log final progress
        if progress_lines:
            activity.logger.info(f"ffmpeg complete: {progress_lines[-1]}")
        
        # Step 5: Upload transcoded video to 'encoded' bucket with .mp4 extension
        encoded_video_id = f"{video_id}_720p.mp4"
        
        activity.logger.info(f"Uploading transcoded video to encoded/{encoded_video_id}")
        upload_success = storage.upload_file(
            file_path=temp_output_path,
            bucket_name="encoded",
            object_name=encoded_video_id
        )
        
        if not upload_success:
            raise RuntimeError(f"Failed to upload transcoded video to MinIO")
        
        # Step 6: Get output file size
        output_size = os.path.getsize(temp_output_path)
        input_size = os.path.getsize(temp_input_path)
        compression_ratio = (1 - output_size / input_size) * 100
        
        result_data = {
            "video_id": video_id,
            "original_resolution": f"{original_width}x{original_height}",
            "target_resolution": "1280x720",
            "encoded_video_id": encoded_video_id,
            "success": True,
            "input_file_size": input_size,
            "output_file_size": output_size,
            "compression_ratio": f"{compression_ratio:.1f}%"
        }
        
        activity.logger.info(
            f"Successfully transcoded {video_id}: "
            f"{input_size / (1024*1024):.1f}MB → {output_size / (1024*1024):.1f}MB "
            f"({compression_ratio:.1f}% reduction)"
        )
        
        return result_data
    
    except RuntimeError as e:
        activity.logger.error(f"Runtime error: {e}")
        raise
    except subprocess.TimeoutExpired:
        activity.logger.error(f"ffmpeg timeout for video {video_id}")
        raise RuntimeError("ffmpeg execution timed out (>10 minutes)")
    except Exception as e:
        activity.logger.error(f"Error transcoding {video_id}: {e}")
        raise
    finally:
        # Step 7: Cleanup temporary files
        if temp_input_path and Path(temp_input_path).exists():
            Path(temp_input_path).unlink()
            activity.logger.info(f"Cleaned up input: {temp_input_path}")
        
        if temp_output_path and Path(temp_output_path).exists():
            Path(temp_output_path).unlink()
            activity.logger.info(f"Cleaned up output: {temp_output_path}")
