"""
Temporal workflow definitions for video processing.

Purpose: Orchestrate video processing pipeline with parallel chunk-based transcoding.
Consumers: Workflow workers polling 'video-tasks' queue.
Logic:
  1. Download from YouTube (if URL provided)
  2. Extract metadata
  3. Determine target resolutions (only downscale)
  4. Split video into chunks at GOP boundaries
  5. Transcode all chunks × resolutions in parallel (to HLS .ts segments)
  6. Generate HLS playlists (variant + master) for adaptive streaming
  7. Return aggregated results with streaming URLs
"""
import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities.download import download_youtube_video
    from worker.activities.metadata import extract_metadata
    from worker.activities.chunked_transcode import (
        split_video,
        transcode_chunk,
        generate_hls_playlist,
        generate_master_playlist,
    )


# Resolution heights for smart selection (only downscale)
RESOLUTION_HEIGHTS = {
    "320p": 320,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
}


def determine_target_resolutions(source_height: int) -> list:
    """
    Determine which resolutions to transcode to based on source.
    
    Only downscales - never upscales (waste of CPU and storage).
    
    Args:
        source_height: Original video height in pixels
        
    Returns:
        List of resolution names to transcode to
        
    Examples:
        1080p source -> ['720p', '480p', '320p']
        720p source  -> ['480p', '320p']
        480p source  -> ['320p']
        320p source  -> [] (no transcoding needed)
    """
    targets = []
    for name, height in sorted(RESOLUTION_HEIGHTS.items(), key=lambda x: -x[1]):
        if height < source_height:
            targets.append(name)
    return targets


@workflow.defn
class VideoWorkflow:
    """
    Video processing workflow with parallel chunk-based multi-resolution transcoding.
    
    Pipeline:
        Download → Metadata → Split → Parallel Transcode Chunks → Generate HLS Playlists
    
    Storage Flow (HLS Streaming Output):
        videos/{video_id}/source/source.mp4                        # Input
            ↓
        videos/{video_id}/source/chunks/chunk_*.mp4                # Split output
        videos/{video_id}/source/manifest.json                     # Ordering metadata
            ↓
        videos/{video_id}/outputs/{res}/segments/seg_*.ts          # HLS segments
        videos/{video_id}/outputs/{res}/playlist.m3u8              # Variant playlist
            ↓
        videos/{video_id}/outputs/master.m3u8                      # Master playlist (ABR)
    
    Smart features:
        - Only downscales (never upscales)
        - Chunk-based parallel execution for large videos
        - Failure isolation: only failed chunks retry
        - Deterministic ordering via manifest
        - Retry policy with exponential backoff
        - HLS output for adaptive bitrate streaming
    """
    
    @workflow.run
    async def run(self, video_id: str, youtube_url: str = None) -> dict:
        """
        Execute the video processing workflow with chunk-based transcoding.
        
        INPUT:
            - video_id: str             → Unique identifier (timestamp_hash)
            - youtube_url: str (opt)    → If provided, downloads from YouTube
            
            Expected MinIO State (if no youtube_url):
                videos/{video_id}/source/source.mp4   → Source video exists
        
        OUTPUT (MinIO - HLS Streaming Structure):
            videos/{video_id}/
                source/
                    source.mp4          → Original video
                    chunks/
                        chunk_0000.mp4, chunk_0001.mp4, ... chunk_N.mp4
                    manifest.json       → {"chunk_count": N, "chunks": [...]}
                outputs/
                    master.m3u8         → Master playlist (adaptive bitrate index)
                    720p/
                        playlist.m3u8   → Variant playlist for 720p
                        segments/       → seg_0000.ts ... seg_N.ts
                    480p/
                        playlist.m3u8   → Variant playlist for 480p
                        segments/       → seg_0000.ts ... seg_N.ts
                    320p/
                        playlist.m3u8   → Variant playlist for 320p  
                        segments/       → seg_0000.ts ... seg_N.ts
        
        OUTPUT (Return):
            {
                "success": bool,
                "video_id": str,
                "metadata": {"width": int, "height": int, "duration": float, ...},
                "source_resolution": "1920x1080",
                "chunk_count": int,
                "hls": {
                    "master_playlist": "{video_id}/outputs/master.m3u8",
                    "variants": [
                        {"resolution": "720p", "playlist": "...", "bandwidth": 2800000},
                        ...
                    ]
                },
                "errors": [...] or None
            }
        
        ACTIVITY STEPS:
        
        1. download_youtube_video (if youtube_url provided)
           Input:  video_id, youtube_url
           Action: • Downloads video using yt-dlp (max 1080p)
                   • Uploads to videos/{video_id}/source/source.mp4
           Output: {"title": str, "duration_seconds": int, "file_size_bytes": int}
        
        2. extract_metadata
           Input:  video_id
           Source: videos/{video_id}/source/source.mp4
           Action: • Runs ffprobe to get width, height, duration, codec
           Output: {"width": 1920, "height": 1080, "duration": 120.5, ...}
        
        3. split_video
           Input:  video_id, chunk_duration=4
           Source: videos/{video_id}/source/source.mp4
           Action: • Splits at GOP boundaries using ffmpeg -f segment -c copy
                   • Creates 4-second chunks (no re-encoding)
                   • Uploads to videos/{video_id}/source/chunks/chunk_NNNN.mp4
                   • Creates manifest with ordering metadata
           Output: videos/{video_id}/source/chunks/chunk_0000..N.mp4
                   videos/{video_id}/source/manifest.json
                   Returns: {"chunk_count": N, "chunks": [{"index": 0, "key": ...}]}
        
        4. transcode_chunk (parallel: chunks × resolutions)
           Input:  video_id, chunk_index, resolution, source_chunk_key
           Source: videos/{video_id}/source/chunks/chunk_NNNN.mp4
           Action: • Downloads source chunk
                   • Transcodes to target resolution using ffmpeg
                   • Outputs MPEG-TS format (.ts) for HLS compatibility
                   • Uploads to videos/{video_id}/outputs/{res}/segments/seg_NNNN.ts
           Output: videos/{video_id}/outputs/{resolution}/segments/seg_NNNN.ts
                   Returns: {"chunk_index": N, "resolution": "720p", "output_key": ...}
           
           Example: 10 chunks × 3 resolutions = 30 parallel tasks
        
        5. generate_hls_playlist (per resolution)
           Input:  video_id, resolution, chunk_count
           Source: videos/{video_id}/outputs/{resolution}/segments/seg_0000..N.ts
           Action: • Verifies all segments exist
                   • Generates .m3u8 playlist referencing segments
                   • Uploads to videos/{video_id}/outputs/{resolution}/playlist.m3u8
           Output: videos/{video_id}/outputs/{resolution}/playlist.m3u8
                   Returns: {"resolution": "720p", "playlist_key": ..., "bandwidth": ...}
        
        6. generate_master_playlist
           Input:  video_id, variants (list of resolution info)
           Action: • Creates master.m3u8 listing all quality levels
                   • Includes bandwidth hints for adaptive streaming
                   • Uploads to videos/{video_id}/outputs/master.m3u8
           Output: videos/{video_id}/outputs/master.m3u8
                   Returns: {"master_playlist_key": ..., "variant_count": N}
        
        FAILURE HANDLING:
            • Each activity retries up to 5 times with exponential backoff
            • If chunk transcoding fails, only that chunk retries
            • If entire resolution fails, continues with other resolutions
            • Workflow succeeds if ≥1 resolution completes successfully
        
        Args:
            video_id: Unique identifier for the video in MinIO
            youtube_url: Optional YouTube URL (if None, assumes video already in MinIO)
            
        Returns:
            Dictionary with success status, metadata, and HLS streaming information
        """
        # Retry policy: max 5 attempts with exponential backoff
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            backoff_coefficient=2.0,
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=5,
        )
        
        # Step 1: Download from YouTube if URL provided
        if youtube_url:
            try:
                workflow.logger.info(f"[{video_id}] Starting YouTube download")
                download_result = await workflow.execute_activity(
                    download_youtube_video,
                    args=[video_id, youtube_url],
                    start_to_close_timeout=timedelta(minutes=5),
                    task_queue="download-queue",
                    retry_policy=retry_policy,
                )
                workflow.logger.info(
                    f"[{video_id}] Download complete: {download_result.get('title')} "
                    f"({download_result.get('file_size_bytes', 0) / 1024 / 1024:.2f} MB)"
                )
            except ActivityError as e:
                workflow.logger.error(f"[{video_id}] Download failed: {e}")
                return {
                    "success": False,
                    "video_id": video_id,
                    "error": "download_failed",
                    "message": str(e.cause),
                }
        
        # Step 2: Extract metadata
        try:
            workflow.logger.info(f"[{video_id}] Extracting metadata")
            metadata = await workflow.execute_activity(
                extract_metadata,
                video_id,
                start_to_close_timeout=timedelta(seconds=60),
                task_queue="metadata-queue",
                retry_policy=retry_policy,
            )
            source_height = metadata.get("height", 0)
            source_width = metadata.get("width", 0)
            workflow.logger.info(f"[{video_id}] Metadata: {source_width}x{source_height}")
            
        except ActivityError as e:
            workflow.logger.error(f"[{video_id}] Metadata extraction failed: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "error": "metadata_extraction_failed",
                "message": str(e.cause),
            }
        
        # Step 3: Determine target resolutions (smart downscale only)
        target_resolutions = determine_target_resolutions(source_height)
        
        if not target_resolutions:
            workflow.logger.info(f"[{video_id}] Source is already lowest resolution, skipping transcode")
            return {
                "success": True,
                "video_id": video_id,
                "metadata": metadata,
                "transcoded": [],
                "message": "Source video is already at minimum resolution",
            }
        
        workflow.logger.info(f"[{video_id}] Target resolutions: {target_resolutions}")
        
        # Step 4: Split video into chunks
        try:
            workflow.logger.info(f"[{video_id}] Splitting video into chunks")
            split_result = await workflow.execute_activity(
                split_video,
                args=[video_id, 4],  # 4 second chunks
                start_to_close_timeout=timedelta(minutes=10),
                task_queue="split-queue",
                retry_policy=retry_policy,
            )
            chunks = split_result.get("chunks", [])
            chunk_count = split_result.get("chunk_count", 0)
            workflow.logger.info(f"[{video_id}] Split complete: {chunk_count} chunks")
            
        except ActivityError as e:
            workflow.logger.error(f"[{video_id}] Split failed: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "error": "split_failed",
                "message": str(e.cause),
            }
        
        # Step 5: Transcode all chunks × resolutions in PARALLEL
        # Create tasks for every (chunk, resolution) combination
        transcode_tasks = []
        
        for resolution in target_resolutions:
            for chunk in chunks:
                task = workflow.execute_activity(
                    transcode_chunk,
                    args=[video_id, chunk["index"], resolution, chunk["key"]],
                    start_to_close_timeout=timedelta(minutes=5),
                    task_queue="transcode-queue",
                    retry_policy=retry_policy,
                )
                transcode_tasks.append({
                    "task": task,
                    "resolution": resolution,
                    "chunk_index": chunk["index"]
                })
        
        total_tasks = len(transcode_tasks)
        workflow.logger.info(
            f"[{video_id}] Starting {total_tasks} parallel transcode tasks "
            f"({chunk_count} chunks × {len(target_resolutions)} resolutions)"
        )
        
        # Execute all transcode tasks in parallel
        completed_tasks = await asyncio.gather(
            *[t["task"] for t in transcode_tasks],
            return_exceptions=True
        )
        
        # Process results and track failures
        transcode_errors = []
        successful_by_resolution = {res: 0 for res in target_resolutions}
        
        for i, task_info in enumerate(transcode_tasks):
            result = completed_tasks[i]
            if isinstance(result, Exception):
                workflow.logger.error(
                    f"[{video_id}] Chunk {task_info['chunk_index']} {task_info['resolution']} failed: {result}"
                )
                transcode_errors.append({
                    "resolution": task_info["resolution"],
                    "chunk_index": task_info["chunk_index"],
                    "error": str(result),
                })
            else:
                successful_by_resolution[task_info["resolution"]] += 1
        
        workflow.logger.info(
            f"[{video_id}] Transcode complete: "
            f"{total_tasks - len(transcode_errors)} succeeded, {len(transcode_errors)} failed"
        )
        
        # Check if any resolution has all chunks transcoded
        if transcode_errors:
            # Check which resolutions are fully complete
            complete_resolutions = [
                res for res, count in successful_by_resolution.items()
                if count == chunk_count
            ]
            incomplete_resolutions = [
                res for res, count in successful_by_resolution.items()
                if count < chunk_count
            ]
            
            if not complete_resolutions:
                return {
                    "success": False,
                    "video_id": video_id,
                    "error": "transcode_failed",
                    "message": f"No resolution fully transcoded. Errors: {len(transcode_errors)}",
                    "errors": transcode_errors,
                }
            
            # Continue with complete resolutions only
            target_resolutions = complete_resolutions
            workflow.logger.warning(
                f"[{video_id}] Proceeding with complete resolutions: {complete_resolutions}. "
                f"Incomplete: {incomplete_resolutions}"
            )
        
        # Step 6: Generate HLS playlists for each resolution (replaces merge_segments)
        # This is instant since we just create text files referencing existing segments
        playlist_tasks = []
        
        for resolution in target_resolutions:
            task = workflow.execute_activity(
                generate_hls_playlist,
                args=[video_id, resolution, chunk_count],
                start_to_close_timeout=timedelta(seconds=60),
                task_queue="playlist-queue",
                retry_policy=retry_policy,
            )
            playlist_tasks.append({"task": task, "resolution": resolution})
        
        workflow.logger.info(f"[{video_id}] Starting {len(playlist_tasks)} playlist generation tasks")
        
        playlist_results = await asyncio.gather(
            *[t["task"] for t in playlist_tasks],
            return_exceptions=True
        )
        
        # Process playlist results
        variants = []
        playlist_errors = []
        
        for i, task_info in enumerate(playlist_tasks):
            result = playlist_results[i]
            if isinstance(result, Exception):
                workflow.logger.error(
                    f"[{video_id}] Playlist {task_info['resolution']} failed: {result}"
                )
                playlist_errors.append({
                    "resolution": task_info["resolution"],
                    "error": str(result),
                })
            else:
                variants.append(result)
                workflow.logger.info(f"[{video_id}] Playlist {task_info['resolution']} complete")
        
        # Step 7: Generate master playlist if we have any successful variants
        master_result = None
        if variants:
            try:
                workflow.logger.info(f"[{video_id}] Generating master playlist")
                master_result = await workflow.execute_activity(
                    generate_master_playlist,
                    args=[video_id, variants],
                    start_to_close_timeout=timedelta(seconds=30),
                    task_queue="playlist-queue",
                    retry_policy=retry_policy,
                )
                workflow.logger.info(f"[{video_id}] Master playlist complete")
            except ActivityError as e:
                workflow.logger.error(f"[{video_id}] Master playlist failed: {e}")
                playlist_errors.append({
                    "resolution": "master",
                    "error": str(e.cause),
                })
        
        workflow.logger.info(
            f"[{video_id}] Workflow complete: "
            f"{len(variants)} resolutions, {chunk_count} chunks processed"
        )
        
        # Return aggregated results with HLS info
        all_errors = transcode_errors + playlist_errors
        return {
            "success": len(playlist_errors) == 0 and len(variants) > 0,
            "video_id": video_id,
            "metadata": metadata,
            "source_resolution": f"{source_width}x{source_height}",
            "chunk_count": chunk_count,
            "hls": {
                "master_playlist": master_result.get("master_playlist_key") if master_result else None,
                "variants": [
                    {
                        "resolution": v["resolution"],
                        "playlist": v["playlist_key"],
                        "bandwidth": v.get("bandwidth"),
                        "segment_count": v.get("segment_count"),
                    }
                    for v in variants
                ],
            },
            "errors": all_errors if all_errors else None,
        }
