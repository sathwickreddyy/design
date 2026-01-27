"""
Chunked transcoding activities for large video processing with HLS output.

Purpose: Split videos into chunks, transcode in parallel, and generate HLS playlists.
Consumers: Workers polling 'split-queue', 'transcode-queue', 'playlist-queue'.
Logic:
  - split_video: Split source into GOP-aligned chunks + manifest
  - transcode_chunk: Transcode a single chunk to HLS-compatible .ts segment
  - generate_hls_playlist: Create m3u8 playlists for adaptive streaming
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
DEFAULT_CHUNK_DURATION = 4


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
            object_name=StoragePaths.source_video(video_id),
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


def escape_ffmpeg_text(text: str) -> str:
    """
    Escape special characters for FFmpeg drawtext filter.
    
    FFmpeg drawtext filter has specific escaping requirements:
    - Colons must be escaped with backslash
    - Single quotes need special handling
    - Backslashes need doubling
    - Newlines should be removed
    
    Args:
        text: Raw text to escape
        
    Returns:
        Escaped text safe for FFmpeg drawtext
    """
    if not text:
        return ""
    
    # Remove newlines and tabs
    text = text.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
    
    # Escape backslashes first (before adding more)
    text = text.replace('\\', '\\\\')
    
    # Escape single quotes (FFmpeg uses '' to escape ')
    text = text.replace("'", "'\\''")
    
    # Escape colons (required for drawtext filter)
    text = text.replace(':', '\\:')
    
    # Escape other special chars
    text = text.replace('%', '\\%')
    
    return text


def build_watermark_filter(
    text: str,
    position: str = "bottom-right",
    font_size: int = 24,
    opacity: float = 0.5
) -> str:
    """
    Build FFmpeg drawtext filter for watermark overlay.
    
    Positions:
        - top-left: x=10:y=10
        - top-right: x=w-tw-10:y=10
        - bottom-left: x=10:y=h-th-10
        - bottom-right: x=w-tw-10:y=h-th-10
        - center: x=(w-tw)/2:y=(h-th)/2
    
    Args:
        text: Watermark text
        position: Position on video frame
        font_size: Font size in pixels
        opacity: Background box opacity (0-1)
        
    Returns:
        FFmpeg drawtext filter string
    """
    escaped_text = escape_ffmpeg_text(text)
    
    # Position coordinates
    positions = {
        "top-left": "x=10:y=10",
        "top-right": "x=w-tw-10:y=10",
        "bottom-left": "x=10:y=h-th-10",
        "bottom-right": "x=w-tw-10:y=h-th-10",
        "center": "x=(w-tw)/2:y=(h-th)/2"
    }
    
    pos = positions.get(position, positions["bottom-right"])
    
    # Build the filter
    # box=1 enables background box, boxcolor with alpha for semi-transparent
    filter_str = (
        f"drawtext=text='{escaped_text}':"
        f"fontcolor=white:fontsize={font_size}:"
        f"box=1:boxcolor=black@{opacity}:boxborderw=5:"
        f"{pos}"
    )
    
    return filter_str


@activity.defn
async def transcode_chunk(
    video_id: str,
    chunk_index: int,
    resolution: str,
    source_chunk_key: str,
    watermark_text: str = None,
    watermark_position: str = "bottom-right",
    watermark_font_size: int = 24,
    watermark_opacity: float = 0.5
) -> dict:
    """
    Transcode a single chunk to target resolution with optional watermark.
    
    Purpose: Process one chunk independently for parallel execution.
    Consumers: Workflow orchestrator spawning parallel tasks.
    Logic:
      1. Download source chunk from MinIO
      2. Build video filter (scale + optional watermark)
      3. Transcode to target resolution using ffmpeg
      4. Upload encoded chunk to MinIO: videos/{video_id}/outputs/{resolution}/segments/
      5. Cleanup temp files
    
    Args:
        video_id: Unique identifier for the video
        chunk_index: Index of the chunk (for ordering)
        resolution: Target resolution (e.g., "720p")
        source_chunk_key: MinIO key for the source chunk
        watermark_text: Optional text to overlay on video
        watermark_position: Position of watermark (top-left, top-right, bottom-left, bottom-right)
        watermark_font_size: Font size for watermark text
        watermark_opacity: Opacity of watermark background (0-1)
        
    Returns:
        Dictionary with:
        - video_id: str
        - chunk_index: int
        - resolution: str
        - output_key: str (path to encoded chunk in MinIO)
        - has_watermark: bool
        - success: bool
    """
    activity.logger.info(
        f"[{video_id}] Transcoding chunk {chunk_index} to {resolution}"
        + (f" with watermark" if watermark_text else "")
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
        
        # Step 2: Build video filter chain
        # Start with scale filter
        filters = [config["scale"]]
        
        # Add watermark if provided
        has_watermark = False
        if watermark_text and watermark_text.strip():
            watermark_filter = build_watermark_filter(
                text=watermark_text.strip(),
                position=watermark_position,
                font_size=watermark_font_size,
                opacity=watermark_opacity
            )
            filters.append(watermark_filter)
            has_watermark = True
            activity.logger.debug(f"[{video_id}] Watermark filter: {watermark_filter}")
        
        # Combine filters with comma separator
        video_filter = ",".join(filters)
        
        # Step 3: Transcode chunk to HLS-compatible MPEG-TS format
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{resolution}.ts") as tmp_out:
            temp_output_path = tmp_out.name
        
        cmd = [
            "ffmpeg",
            "-i", temp_input_path,
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-f", "mpegts",  # Output as MPEG-TS for HLS compatibility
            "-muxdelay", "0",  # Minimize muxing delay
            "-muxpreload", "0",  # No preload buffering
            "-avoid_negative_ts", "make_zero",  # Ensure positive timestamps
            "-fflags", "+genpts+igndts",  # Generate PTS, ignore input DTS discontinuities
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
        
        
        # Step 4: Upload encoded chunk
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
            + (f" (watermarked)" if has_watermark else "")
        )
        
        return {
            "video_id": video_id,
            "chunk_index": chunk_index,
            "resolution": resolution,
            "output_key": output_key,
            "input_size_bytes": input_size,
            "output_size_bytes": output_size,
            "has_watermark": has_watermark,
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


# HLS Configuration: Bandwidth estimates for adaptive bitrate selection
HLS_BANDWIDTH = {
    "320p": 800000,    # 800 Kbps
    "480p": 1400000,   # 1.4 Mbps
    "720p": 2800000,   # 2.8 Mbps
    "1080p": 5000000,  # 5 Mbps
}

# Default segment duration (should match split_video chunk_duration)
HLS_SEGMENT_DURATION = 4


@activity.defn
async def generate_hls_playlist(
    video_id: str,
    resolution: str,
    chunk_count: int,
    segment_duration: float = HLS_SEGMENT_DURATION
) -> dict:
    """
    Generate HLS variant playlist (.m3u8) for a resolution.
    
    Purpose: Create streaming-ready playlist referencing transcoded segments.
    Consumers: Workflow orchestrator after all chunks are transcoded.
    
    Benefits over merge_segments:
      - No re-encoding or file merging required (instant)
      - Streaming-ready output for immediate playback
      - Enables adaptive bitrate switching
      - Reduced storage (no duplicate merged files)
    
    Logic:
      1. Verify all segments exist in MinIO
      2. Generate m3u8 playlist content
      3. Upload playlist to MinIO
    
    Args:
        video_id: Unique identifier for the video
        resolution: Target resolution (e.g., "720p")
        chunk_count: Number of segments in the playlist
        segment_duration: Duration of each segment in seconds
        
    Returns:
        Dictionary with:
        - video_id: str
        - resolution: str
        - playlist_key: str (path to .m3u8 in MinIO)
        - segment_count: int
        - success: bool
    """
    activity.logger.info(
        f"[{video_id}] Generating HLS playlist for {resolution} ({chunk_count} segments)"
    )
    
    storage = MinIOStorage()
    
    try:
        # Step 1: Verify all segments exist
        missing_segments = []
        segment_keys = []
        
        for idx in range(chunk_count):
            segment_key = StoragePaths.output_segment(video_id, resolution, idx)
            segment_keys.append(segment_key)
            
            if not storage.file_exists("videos", segment_key):
                missing_segments.append(idx)
        
        if missing_segments:
            raise RuntimeError(
                f"Missing segments for {resolution}: {missing_segments[:10]}" +
                (f"... and {len(missing_segments) - 10} more" if len(missing_segments) > 10 else "")
            )
        
        activity.logger.info(f"[{video_id}] Verified {chunk_count} segments exist")
        
        # Step 2: Generate m3u8 playlist content
        # HLS playlist format (version 3 for broad compatibility)
        playlist_lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{int(segment_duration) + 1}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-ALLOW-CACHE:YES",
        ]
        
        # Add each segment with discontinuity tags
        # Each transcoded chunk has independent timestamps, so we mark discontinuities
        for idx in range(chunk_count):
            # Add discontinuity tag for each segment after the first
            # This tells players to expect timestamp resets
            if idx > 0:
                playlist_lines.append("#EXT-X-DISCONTINUITY")
            
            segment_filename = f"segments/seg_{idx:04d}.ts"
            playlist_lines.append(f"#EXTINF:{segment_duration:.3f},")
            playlist_lines.append(segment_filename)
        
        # End of playlist marker (required for VOD)
        playlist_lines.append("#EXT-X-ENDLIST")
        
        playlist_content = "\n".join(playlist_lines)
        
        # Step 3: Upload variant playlist
        playlist_key = StoragePaths.variant_playlist(video_id, resolution)
        
        upload_success = storage.upload_fileobj(
            file_data=playlist_content.encode('utf-8'),
            bucket_name="videos",
            object_name=playlist_key
        )
        
        if not upload_success:
            raise RuntimeError(f"Failed to upload playlist for {resolution}")
        
        activity.logger.info(
            f"[{video_id}] HLS playlist generated for {resolution}: "
            f"videos/{playlist_key} ({chunk_count} segments)"
        )
        
        return {
            "video_id": video_id,
            "resolution": resolution,
            "playlist_key": playlist_key,
            "segment_count": chunk_count,
            "bandwidth": HLS_BANDWIDTH.get(resolution, 1000000),
            "success": True
        }
        
    except Exception as e:
        activity.logger.error(f"[{video_id}] Playlist generation failed for {resolution}: {e}")
        raise


@activity.defn
async def generate_master_playlist(
    video_id: str,
    variants: list[dict]
) -> dict:
    """
    Generate HLS master playlist for adaptive bitrate streaming.
    
    Purpose: Create the "menu" that video players use to select quality.
    Consumers: Workflow orchestrator after all variant playlists are created.
    
    The master playlist lists all available quality levels with their
    bandwidth requirements, allowing players to adaptively switch based
    on network conditions.
    
    Args:
        video_id: Unique identifier for the video
        variants: List of variant info dicts with resolution, bandwidth, playlist_key
        
    Returns:
        Dictionary with:
        - video_id: str
        - master_playlist_key: str
        - variant_count: int
        - success: bool
    """
    activity.logger.info(
        f"[{video_id}] Generating master playlist for {len(variants)} variants"
    )
    
    storage = MinIOStorage()
    
    try:
        # Build master playlist content
        # Sort variants by bandwidth (highest first for better initial quality)
        sorted_variants = sorted(variants, key=lambda v: v.get("bandwidth", 0), reverse=True)
        
        playlist_lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
        ]
        
        for variant in sorted_variants:
            resolution = variant["resolution"]
            bandwidth = variant.get("bandwidth", HLS_BANDWIDTH.get(resolution, 1000000))
            height = RESOLUTION_CONFIG.get(resolution, {}).get("height", 720)
            
            # Calculate approximate width (16:9 aspect ratio)
            width = int(height * 16 / 9)
            
            # EXT-X-STREAM-INF describes each variant
            playlist_lines.append(
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={width}x{height},NAME=\"{resolution}\""
            )
            # Relative path to variant playlist
            playlist_lines.append(f"{resolution}/playlist.m3u8")
        
        playlist_content = "\n".join(playlist_lines)
        
        # Upload master playlist
        master_key = StoragePaths.master_playlist(video_id)
        
        upload_success = storage.upload_fileobj(
            file_data=playlist_content.encode('utf-8'),
            bucket_name="videos",
            object_name=master_key
        )
        
        if not upload_success:
            raise RuntimeError("Failed to upload master playlist")
        
        activity.logger.info(
            f"[{video_id}] Master playlist generated: videos/{master_key}"
        )
        
        return {
            "video_id": video_id,
            "master_playlist_key": master_key,
            "variant_count": len(variants),
            "variants": [v["resolution"] for v in sorted_variants],
            "success": True
        }
        
    except Exception as e:
        activity.logger.error(f"[{video_id}] Master playlist generation failed: {e}")
        raise


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


# Export all activity functions
__all__ = [
    "split_video",
    "transcode_chunk",
    "generate_hls_playlist",
    "generate_master_playlist",
    "cleanup_source_chunks",
]
