"""
Chunked transcoding activities for large video processing.

Purpose: Split videos into chunks, transcode in parallel, and merge results.
Consumers: Workers polling 'split-queue', 'transcode-queue', 'merge-queue'.
Logic:
  - split_video: Split source into GOP-aligned chunks + manifest
  - transcode_chunk: Transcode a single chunk to target resolution
  - merge_segments: Combine transcoded chunks into final video
"""
import os
import json
import subprocess
import tempfile
from pathlib import Path
from temporalio import activity
from shared.storage import MinIOStorage, StoragePaths


# Resolution configurations
RESOLUTION_CONFIG = {
    "320p": {"scale": "scale=-2:320", "height": 320},
    "480p": {"scale": "scale=-2:480", "height": 480},
    "720p": {"scale": "scale=-2:720", "height": 720},
    "1080p": {"scale": "scale=-2:1080", "height": 1080},
}

# Default chunk duration in seconds (4s is common for HLS/DASH)
# Configurable via CHUNK_DURATION_SECONDS environment variable
DEFAULT_CHUNK_DURATION = int(os.getenv("CHUNK_DURATION_SECONDS", "4"))


@activity.defn
async def split_video(video_id: str, chunk_duration: int = DEFAULT_CHUNK_DURATION) -> dict:
    """
    Split source video into GOP-aligned chunks.
    
    Purpose: Prepare video for parallel transcoding by splitting at keyframes.
    Consumers: Workflow orchestrator after metadata extraction.
    Logic:
      1. Download source video from MinIO
      2. Use ffmpeg to split at keyframes (GOP boundaries)
      3. Upload chunks to MinIO: videos/{video_id}/chunks/source/
      4. Create and upload manifest with chunk metadata
      5. Cleanup temp files
    
    Args:
        video_id: Unique identifier for the video
        chunk_duration: Target duration per chunk in seconds (default: 4)
        
    Returns:
        Dictionary with:
        - video_id: str
        - chunk_count: int
        - chunks: list of chunk info dicts
        - manifest_key: str (path to manifest in MinIO)
    """
    activity.logger.info(f"[{video_id}] Starting video split (chunk_duration={chunk_duration}s)")
    
    storage = MinIOStorage()
    temp_dir = None
    temp_input_path = None
    
    try:
        # Create temp directory for chunks
        temp_dir = tempfile.mkdtemp(prefix=f"split_{video_id}_")
        
        # Step 1: Download source video
        activity.logger.info(f"[{video_id}] Downloading source video")
        temp_input_path = os.path.join(temp_dir, "source.mp4")
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=f"{video_id}.mp4",  # Legacy path for uploaded videos
            file_path=temp_input_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download video {video_id} from MinIO")
        
        input_size = os.path.getsize(temp_input_path)
        activity.logger.info(f"[{video_id}] Source size: {input_size / (1024*1024):.2f} MB")
        
        # Step 2: Split video using ffmpeg segment muxer
        # -f segment: Use segment muxer
        # -segment_time: Target segment duration
        # -reset_timestamps 1: Reset timestamps for each segment
        # -c copy: Copy streams without re-encoding (fast)
        # -force_key_frames: Force keyframes at segment boundaries
        chunk_pattern = os.path.join(temp_dir, "chunk_%04d.mp4")
        
        cmd = [
            "ffmpeg",
            "-i", temp_input_path,
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(chunk_duration),
            "-reset_timestamps", "1",
            "-map", "0",
            "-y",
            chunk_pattern
        ]
        
        activity.logger.info(f"[{video_id}] Running ffmpeg split")
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if process.returncode != 0:
            activity.logger.error(f"[{video_id}] ffmpeg split failed: {process.stderr[-500:]}")
            raise RuntimeError(f"ffmpeg split failed: {process.stderr[-200:]}")
        
        # Step 3: Collect and upload chunks
        chunk_files = sorted(Path(temp_dir).glob("chunk_*.mp4"))
        chunks = []
        
        activity.logger.info(f"[{video_id}] Uploading {len(chunk_files)} chunks")
        
        for idx, chunk_file in enumerate(chunk_files):
            chunk_size = chunk_file.stat().st_size
            chunk_key = StoragePaths.source_chunk(video_id, idx)
            
            # Upload chunk to MinIO
            upload_success = storage.upload_file(
                file_path=str(chunk_file),
                bucket_name="videos",
                object_name=chunk_key
            )
            
            if not upload_success:
                raise RuntimeError(f"Failed to upload chunk {idx}")
            
            chunks.append({
                "index": idx,
                "key": chunk_key,
                "size_bytes": chunk_size
            })
            
            activity.logger.debug(f"[{video_id}] Uploaded chunk {idx}: {chunk_size / 1024:.1f} KB")
        
        # Step 4: Create and upload manifest
        manifest = {
            "video_id": video_id,
            "chunk_count": len(chunks),
            "chunk_duration_target": chunk_duration,
            "source_size_bytes": input_size,
            "chunks": chunks
        }
        
        manifest_key = StoragePaths.source_manifest(video_id)
        manifest_bytes = json.dumps(manifest, indent=2).encode('utf-8')
        
        storage.upload_fileobj(
            file_data=manifest_bytes,
            bucket_name="videos",
            object_name=manifest_key
        )
        
        activity.logger.info(
            f"[{video_id}] Split complete: {len(chunks)} chunks, "
            f"manifest at {manifest_key}"
        )
        
        return {
            "video_id": video_id,
            "chunk_count": len(chunks),
            "chunks": chunks,
            "manifest_key": manifest_key,
            "success": True
        }
        
    except subprocess.TimeoutExpired:
        activity.logger.error(f"[{video_id}] ffmpeg split timeout")
        raise RuntimeError("ffmpeg split timed out")
    except Exception as e:
        activity.logger.error(f"[{video_id}] Split failed: {e}")
        raise
    finally:
        # Cleanup temp directory
        if temp_dir and Path(temp_dir).exists():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


@activity.defn
async def transcode_chunk(
    video_id: str,
    chunk_index: int,
    resolution: str,
    source_chunk_key: str
) -> dict:
    """
    Transcode a single chunk to target resolution.
    
    Purpose: Process one chunk independently for parallel execution.
    Consumers: Workflow orchestrator spawning parallel tasks.
    Logic:
      1. Download source chunk from MinIO
      2. Transcode to target resolution using ffmpeg
      3. Upload encoded chunk to MinIO: videos/{video_id}/outputs/{resolution}/segments/
      4. Cleanup temp files
    
    Args:
        video_id: Unique identifier for the video
        chunk_index: Index of the chunk (for ordering)
        resolution: Target resolution (e.g., "720p")
        source_chunk_key: MinIO key for the source chunk
        
    Returns:
        Dictionary with:
        - video_id: str
        - chunk_index: int
        - resolution: str
        - output_key: str (path to encoded chunk in MinIO)
        - success: bool
    """
    activity.logger.info(
        f"[{video_id}] Transcoding chunk {chunk_index} to {resolution}"
    )
    
    if resolution not in RESOLUTION_CONFIG:
        raise ValueError(f"Unknown resolution: {resolution}")
    
    config = RESOLUTION_CONFIG[resolution]
    storage = MinIOStorage()
    temp_input_path = None
    temp_output_path = None
    
    try:
        # Step 1: Download source chunk
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_in:
            temp_input_path = tmp_in.name
        
        success = storage.download_file(
            bucket_name="videos",
            object_name=source_chunk_key,
            file_path=temp_input_path
        )
        
        if not success:
            raise RuntimeError(f"Failed to download chunk {source_chunk_key}")
        
        # Step 2: Transcode chunk
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{resolution}.mp4") as tmp_out:
            temp_output_path = tmp_out.name
        
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
            "-y",
            temp_output_path
        ]
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 min per chunk should be plenty
        )
        
        if process.returncode != 0:
            activity.logger.error(
                f"[{video_id}] ffmpeg failed for chunk {chunk_index}: {process.stderr[-300:]}"
            )
            raise RuntimeError(f"ffmpeg failed for chunk {chunk_index}")
        
        # Step 3: Upload encoded chunk
        output_key = StoragePaths.output_segment(video_id, resolution, chunk_index)
        
        upload_success = storage.upload_file(
            file_path=temp_output_path,
            bucket_name="videos",
            object_name=output_key
        )
        
        if not upload_success:
            raise RuntimeError(f"Failed to upload encoded chunk {chunk_index}")
        
        output_size = os.path.getsize(temp_output_path)
        input_size = os.path.getsize(temp_input_path)
        
        activity.logger.info(
            f"[{video_id}] Chunk {chunk_index} -> {resolution} complete: "
            f"{input_size / 1024:.1f}KB -> {output_size / 1024:.1f}KB"
        )
        
        return {
            "video_id": video_id,
            "chunk_index": chunk_index,
            "resolution": resolution,
            "output_key": output_key,
            "input_size_bytes": input_size,
            "output_size_bytes": output_size,
            "success": True
        }
        
    except subprocess.TimeoutExpired:
        activity.logger.error(f"[{video_id}] ffmpeg timeout for chunk {chunk_index}")
        raise RuntimeError(f"ffmpeg timed out for chunk {chunk_index}")
    except Exception as e:
        activity.logger.error(f"[{video_id}] Transcode chunk {chunk_index} failed: {e}")
        raise
    finally:
        # Cleanup
        if temp_input_path and Path(temp_input_path).exists():
            Path(temp_input_path).unlink()
        if temp_output_path and Path(temp_output_path).exists():
            Path(temp_output_path).unlink()


@activity.defn
async def merge_segments(video_id: str, resolution: str, chunk_count: int) -> dict:
    """
    Merge transcoded chunks into final video for a resolution.
    
    Purpose: Combine parallel-processed chunks into playable video.
    Consumers: Workflow orchestrator after all chunks are transcoded.
    Logic:
      1. Download all encoded segments from MinIO (in order)
      2. Create concat file for ffmpeg
      3. Use ffmpeg concat demuxer to merge
      4. Upload final video to encoded bucket
      5. Cleanup temp files
    
    Args:
        video_id: Unique identifier for the video
        resolution: Target resolution (e.g., "720p")
        chunk_count: Number of chunks to merge
        
    Returns:
        Dictionary with:
        - video_id: str
        - resolution: str
        - output_key: str (path to final video)
        - success: bool
    """
    activity.logger.info(
        f"[{video_id}] Merging {chunk_count} segments for {resolution}"
    )
    
    storage = MinIOStorage()
    temp_dir = None
    
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"merge_{video_id}_{resolution}_")
        
        # Step 1: Download all segments in order
        segment_paths = []
        
        for idx in range(chunk_count):
            segment_key = StoragePaths.output_segment(video_id, resolution, idx)
            local_path = os.path.join(temp_dir, f"seg_{idx:04d}.mp4")
            
            success = storage.download_file(
                bucket_name="videos",
                object_name=segment_key,
                file_path=local_path
            )
            
            if not success:
                raise RuntimeError(f"Failed to download segment {idx} for {resolution}")
            
            segment_paths.append(local_path)
        
        activity.logger.info(f"[{video_id}] Downloaded {len(segment_paths)} segments")
        
        # Step 2: Create concat file
        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, 'w') as f:
            for path in segment_paths:
                # ffmpeg concat requires escaped paths
                escaped_path = path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        
        # Step 3: Merge using ffmpeg concat demuxer
        output_path = os.path.join(temp_dir, f"{video_id}_{resolution}.mp4")
        
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        
        activity.logger.info(f"[{video_id}] Running ffmpeg merge for {resolution}")
        
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if process.returncode != 0:
            activity.logger.error(f"[{video_id}] ffmpeg merge failed: {process.stderr[-300:]}")
            raise RuntimeError(f"ffmpeg merge failed for {resolution}")
        
        # Step 4: Upload final video
        final_key = StoragePaths.final_video(video_id, resolution)
        
        upload_success = storage.upload_file(
            file_path=output_path,
            bucket_name="encoded",
            object_name=final_key
        )
        
        if not upload_success:
            raise RuntimeError(f"Failed to upload final {resolution} video")
        
        output_size = os.path.getsize(output_path)
        
        activity.logger.info(
            f"[{video_id}] Merge complete for {resolution}: "
            f"{output_size / (1024*1024):.2f} MB -> encoded/{final_key}"
        )
        
        return {
            "video_id": video_id,
            "resolution": resolution,
            "output_key": final_key,
            "output_size_bytes": output_size,
            "success": True
        }
        
    except subprocess.TimeoutExpired:
        activity.logger.error(f"[{video_id}] ffmpeg merge timeout for {resolution}")
        raise RuntimeError(f"ffmpeg merge timed out for {resolution}")
    except Exception as e:
        activity.logger.error(f"[{video_id}] Merge failed for {resolution}: {e}")
        raise
    finally:
        # Cleanup temp directory
        if temp_dir and Path(temp_dir).exists():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


@activity.defn
async def cleanup_source_chunks(video_id: str, chunk_count: int) -> dict:
    """
    Clean up source chunks after successful transcoding.
    
    Purpose: Free storage by removing intermediate files.
    Consumers: Workflow orchestrator after all renditions complete.
    Logic:
      1. Delete all source chunks from MinIO
      2. Delete source manifest
    
    Args:
        video_id: Unique identifier for the video
        chunk_count: Number of chunks to delete
        
    Returns:
        Dictionary with cleanup status
    """
    activity.logger.info(f"[{video_id}] Cleaning up {chunk_count} source chunks")
    
    storage = MinIOStorage()
    deleted = 0
    
    try:
        # Delete source chunks
        for idx in range(chunk_count):
            chunk_key = StoragePaths.source_chunk(video_id, idx)
            if storage.delete_file("videos", chunk_key):
                deleted += 1
        
        # Delete source manifest
        manifest_key = StoragePaths.source_manifest(video_id)
        storage.delete_file("videos", manifest_key)
        
        activity.logger.info(f"[{video_id}] Cleanup complete: {deleted} chunks deleted")
        
        return {
            "video_id": video_id,
            "chunks_deleted": deleted,
            "success": True
        }
        
    except Exception as e:
        activity.logger.warning(f"[{video_id}] Cleanup partially failed: {e}")
        return {
            "video_id": video_id,
            "chunks_deleted": deleted,
            "success": False,
            "error": str(e)
        }
