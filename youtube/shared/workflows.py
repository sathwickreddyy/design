"""
Temporal workflow definitions for video processing.

Purpose: Orchestrate video processing pipeline with parallel chunk-based transcoding.
Consumers: Workflow workers polling 'video-tasks' queue.
Logic:
  1. Download from YouTube (if URL provided)
  2. Extract metadata
  3. Determine target resolutions (only downscale)
  4. Split video into chunks at GOP boundaries
  5. Transcode all chunks × resolutions in parallel
    6. Merge chunks per resolution into final videos
    7. Return aggregated results
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
        merge_segments,
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
        Download -> Metadata -> Split -> Parallel Transcode Chunks -> Merge -> Cleanup
    
    Smart features:
        - Only downscales (never upscales)
        - Chunk-based parallel execution for large videos
        - Failure isolation: only failed chunks retry
        - Deterministic ordering via manifest
        - Retry policy with exponential backoff
    """
    
    @workflow.run
    async def run(self, video_id: str, youtube_url: str = None) -> dict:
        """
        Execute the video processing workflow with chunk-based transcoding.
        
        Args:
            video_id: Unique identifier for the video in MinIO
            youtube_url: Optional YouTube URL (if None, assumes video already in MinIO)
            
        Returns:
            Dictionary with:
            - success: bool
            - video_id: str
            - metadata: dict (video metadata)
            - chunk_count: int (number of chunks processed)
            - transcoded: list (results for each resolution)
            - error: str (if failed)
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
        
        # Step 6: Merge chunks for each resolution
        merge_tasks = []
        
        for resolution in target_resolutions:
            task = workflow.execute_activity(
                merge_segments,
                args=[video_id, resolution, chunk_count],
                start_to_close_timeout=timedelta(minutes=10),
                task_queue="merge-queue",
                retry_policy=retry_policy,
            )
            merge_tasks.append({"task": task, "resolution": resolution})
        
        workflow.logger.info(f"[{video_id}] Starting {len(merge_tasks)} merge tasks")
        
        merge_results = await asyncio.gather(
            *[t["task"] for t in merge_tasks],
            return_exceptions=True
        )
        
        # Process merge results
        transcoded = []
        merge_errors = []
        
        for i, task_info in enumerate(merge_tasks):
            result = merge_results[i]
            if isinstance(result, Exception):
                workflow.logger.error(
                    f"[{video_id}] Merge {task_info['resolution']} failed: {result}"
                )
                merge_errors.append({
                    "resolution": task_info["resolution"],
                    "error": str(result),
                })
            else:
                transcoded.append(result)
                workflow.logger.info(f"[{video_id}] Merge {task_info['resolution']} complete")
        
        workflow.logger.info(
            f"[{video_id}] Workflow complete: "
            f"{len(transcoded)} resolutions, {chunk_count} chunks processed"
        )
        
        # Return aggregated results
        all_errors = transcode_errors + merge_errors
        return {
            "success": len(merge_errors) == 0 and len(transcoded) > 0,
            "video_id": video_id,
            "metadata": metadata,
            "source_resolution": f"{source_width}x{source_height}",
            "chunk_count": chunk_count,
            "transcoded": transcoded,
            "errors": all_errors if all_errors else None,
        }
