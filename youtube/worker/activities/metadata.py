"""
Metadata extraction activity
Fast, I/O-bound operations for extracting video metadata using ffprobe
"""
import json
import subprocess
import tempfile
from pathlib import Path
from temporalio import activity
from shared.storage import MinIOStorage


@activity.defn
async def extract_metadata(video_id: str) -> dict:
    """
    Extract video metadata using ffprobe
    
    Args:
        video_id: Unique identifier for the video in MinIO
        
    Returns:
        Dictionary containing video metadata (duration, width, height, fps, codec, etc.)
    """
    activity.logger.info(f"Extracting metadata for video ID: {video_id}")
    
    storage = MinIOStorage()
    temp_video_path = None
    
    try:
        # Download video from MinIO
        activity.logger.info(f"Downloading video {video_id} from MinIO")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
            temp_video_path = tmp_file.name
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=f"{video_id}.mp4",
            file_path=temp_video_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download video {video_id} from MinIO")
        
        # Run ffprobe command
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-print_format", "json",
            temp_video_path
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr}")
        
        # Parse ffprobe output
        ffprobe_data = json.loads(result.stdout)
        
        # Extract key metadata
        metadata = {
            "video_id": video_id,
            "duration": None,
            "width": None,
            "height": None,
            "fps": None,
            "video_codec": None,
            "audio_codec": None,
            "bit_rate": None,
            "format": None,
        }
        
        # Extract format information
        if "format" in ffprobe_data:
            format_info = ffprobe_data["format"]
            metadata["duration"] = float(format_info.get("duration", 0))
            metadata["bit_rate"] = int(format_info.get("bit_rate", 0))
            metadata["format"] = format_info.get("format_name")
        
        # Extract stream information
        if "streams" in ffprobe_data:
            for stream in ffprobe_data["streams"]:
                stream_type = stream.get("codec_type")
                
                if stream_type == "video":
                    metadata["width"] = stream.get("width")
                    metadata["height"] = stream.get("height")
                    metadata["video_codec"] = stream.get("codec_name")
                    
                    # Calculate FPS from r_frame_rate
                    if "r_frame_rate" in stream:
                        try:
                            num, den = stream["r_frame_rate"].split("/")
                            metadata["fps"] = float(num) / float(den)
                        except (ValueError, ZeroDivisionError):
                            metadata["fps"] = None
                
                elif stream_type == "audio":
                    metadata["audio_codec"] = stream.get("codec_name")
        
        activity.logger.info(f"Successfully extracted metadata for {video_id}: {metadata}")
        return metadata
    
    except RuntimeError as e:
        activity.logger.error(f"Runtime error: {e}")
        raise
    except subprocess.TimeoutExpired:
        activity.logger.error(f"ffprobe timeout for video {video_id}")
        raise RuntimeError("ffprobe execution timed out")
    except json.JSONDecodeError as e:
        activity.logger.error(f"Failed to parse ffprobe output: {e}")
        raise
    except Exception as e:
        activity.logger.error(f"Error extracting metadata for {video_id}: {e}")
        raise
    finally:
        # Clean up temporary file
        if temp_video_path and Path(temp_video_path).exists():
            Path(temp_video_path).unlink()
            activity.logger.info(f"Cleaned up temporary file: {temp_video_path}")
