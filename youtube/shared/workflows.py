"""
Temporal workflow definitions for video processing.

Purpose: Orchestrate video processing pipeline with parallel transcoding.
Consumers: Workflow workers polling 'video-tasks' queue.
Logic:
  1. Download from YouTube (if URL provided)
  2. Extract metadata
  3. Determine target resolutions (only downscale)
  4. Execute all transcodes in parallel
  5. Return aggregated results
"""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities.download import download_youtube_video
    from worker.activities.metadata import extract_metadata
    from worker.activities.transcode import (
        transcode_to_320p,
        transcode_to_480p,
        transcode_to_720p,
        transcode_to_1080p,
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
    Video processing workflow with parallel multi-resolution transcoding.
    
    Pipeline:
        Download -> Metadata -> Parallel Transcode (320p, 480p, 720p, 1080p)
    
    Smart features:
        - Only downscales (never upscales)
        - Parallel execution of all target resolutions
        - Retry policy with exponential backoff
    """
    
    @workflow.run
    async def run(self, video_id: str, youtube_url: str = None) -> dict:
        """
        Execute the video processing workflow.
        
        Args:
            video_id: Unique identifier for the video in MinIO
            youtube_url: Optional YouTube URL (if None, assumes video already in MinIO)
            
        Returns:
            Dictionary with:
            - success: bool
            - video_id: str
            - metadata: dict (video metadata)
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
        
        # Step 4: Execute all transcodes in PARALLEL
        # Map resolution names to activity functions
        activity_map = {
            "320p": transcode_to_320p,
            "480p": transcode_to_480p,
            "720p": transcode_to_720p,
            "1080p": transcode_to_1080p,
        }
        
        # Create activity tasks for all target resolutions
        transcode_tasks = []
        for resolution in target_resolutions:
            activity_fn = activity_map[resolution]
            task = workflow.execute_activity(
                activity_fn,
                metadata,
                start_to_close_timeout=timedelta(minutes=15),
                task_queue="transcode-queue",
                retry_policy=retry_policy,
            )
            transcode_tasks.append((resolution, task))
        
        workflow.logger.info(f"[{video_id}] Starting {len(transcode_tasks)} parallel transcode tasks")
        
        # Execute all in parallel and collect results
        transcode_results = []
        transcode_errors = []
        
        # Await all tasks (they run in parallel)
        for resolution, task in transcode_tasks:
            try:
                result = await task
                transcode_results.append(result)
                workflow.logger.info(f"[{video_id}] {resolution} transcode complete")
            except ActivityError as e:
                workflow.logger.error(f"[{video_id}] {resolution} transcode failed: {e}")
                transcode_errors.append({
                    "resolution": resolution,
                    "error": str(e.cause),
                })
        
        workflow.logger.info(
            f"[{video_id}] Transcoding complete: "
            f"{len(transcode_results)} succeeded, {len(transcode_errors)} failed"
        )
        
        # Return aggregated results
        return {
            "success": len(transcode_errors) == 0,
            "video_id": video_id,
            "metadata": metadata,
            "source_resolution": f"{source_width}x{source_height}",
            "transcoded": transcode_results,
            "errors": transcode_errors if transcode_errors else None,
        }
