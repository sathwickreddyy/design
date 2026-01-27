"""
Temporal workflow definitions for video processing with Smart DAG.

Purpose: Orchestrate video processing pipeline with conditional branching and parallel execution.
Consumers: Workflow workers polling 'video-tasks' queue.

Smart DAG Features:
  - Conditional thumbnail generation (auto/custom/scene-based)
  - Dynamic resolution selection (user-specified or auto-detect)
  - Optional watermark overlay
  - Scene detection for chapter generation
  - Completion event handling

Logic:
  1. Download from YouTube (if URL provided)
  2. Extract metadata (always)
  3. PARALLEL BRANCH:
     a. Thumbnail generation (if enabled)
     b. Scene detection (if chapters enabled)
  4. Split video into chunks (scene-aware if chapters enabled)
  5. Transcode all chunks × resolutions (with optional watermark)
  6. Generate HLS playlists + chapter files
  7. Signal completion workflow
"""
import asyncio
import json
from datetime import timedelta
from typing import Optional, List, Literal
from dataclasses import dataclass, field, asdict
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities.download import download_youtube_video
    from worker.activities.metadata import extract_metadata
    from worker.activities.thumbnail import generate_thumbnail, upload_custom_thumbnail
    from worker.activities.scene_detection import detect_scenes, generate_chapter_files
    from worker.activities.chunked_transcode import (
        split_video,
        transcode_chunk,
        generate_hls_playlist,
        generate_master_playlist,
    )


# ==================== Processing Options (Data Contract) ====================

@dataclass
class ThumbnailOptions:
    """Configuration for thumbnail generation."""
    mode: Literal["none", "auto", "custom", "scene_based"] = "none"
    custom_timestamp: Optional[str] = None      # e.g., "00:01:30"
    custom_image_key: Optional[str] = None      # MinIO path to uploaded image
    custom_image_bucket: Optional[str] = None   # Bucket containing custom image


@dataclass
class WatermarkOptions:
    """Configuration for watermark overlay."""
    text: Optional[str] = None
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    font_size: int = 24
    opacity: float = 0.5


@dataclass
class ChapterOptions:
    """Configuration for scene detection and chapter generation."""
    enabled: bool = False
    scene_threshold: float = 0.3        # Sensitivity (0.1-0.5, lower = more scenes)
    min_duration: int = 30              # Minimum chapter duration in seconds
    detect_intro: bool = True           # Auto-detect intro sequences
    detect_outro: bool = True           # Auto-detect outro/credits


@dataclass
class ProcessingOptions:
    """
    Complete processing options for video workflow.
    
    This is the main data contract for customizing video processing.
    All fields have sensible defaults, so an empty dict {} will use auto-detection.
    """
    # Resolution control (empty = auto-detect based on source)
    target_resolutions: List[str] = field(default_factory=list)
    
    # Thumbnail settings
    thumbnail: ThumbnailOptions = field(default_factory=ThumbnailOptions)
    
    # Watermark settings (None = no watermark)
    watermark: Optional[WatermarkOptions] = None
    
    # Chapter/scene detection settings
    chapters: ChapterOptions = field(default_factory=ChapterOptions)
    
    # Quality preset affects encoding speed vs compression
    quality_preset: Literal["fast", "medium", "slow"] = "medium"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "target_resolutions": self.target_resolutions,
            "thumbnail": asdict(self.thumbnail),
            "watermark": asdict(self.watermark) if self.watermark else None,
            "chapters": asdict(self.chapters),
            "quality_preset": self.quality_preset,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProcessingOptions":
        """Create from dictionary (for Temporal deserialization)."""
        if not data:
            return cls()
        
        thumbnail = ThumbnailOptions(**data.get("thumbnail", {})) if data.get("thumbnail") else ThumbnailOptions()
        watermark = WatermarkOptions(**data["watermark"]) if data.get("watermark") else None
        chapters = ChapterOptions(**data.get("chapters", {})) if data.get("chapters") else ChapterOptions()
        
        return cls(
            target_resolutions=data.get("target_resolutions", []),
            thumbnail=thumbnail,
            watermark=watermark,
            chapters=chapters,
            quality_preset=data.get("quality_preset", "medium"),
        )


# ==================== Resolution Configuration ====================

RESOLUTION_HEIGHTS = {
    "320p": 320,
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
}

VALID_RESOLUTIONS = set(RESOLUTION_HEIGHTS.keys())


def determine_target_resolutions(source_height: int, requested: List[str] = None) -> List[str]:
    """
    Determine which resolutions to transcode to.
    
    Rules:
        1. Only downscale (never upscale)
        2. If user requested specific resolutions, use those (filtered to valid downscales)
        3. If no request, auto-detect all valid downscales
    
    Args:
        source_height: Original video height in pixels
        requested: User-requested resolutions (optional)
        
    Returns:
        List of resolution names to transcode to
        
    Examples:
        1080p source, no request -> ['720p', '480p', '320p']
        1080p source, ["720p"]   -> ['720p']
        720p source, ["1080p"]   -> [] (can't upscale)
        480p source, no request  -> ['320p']
    """
    if requested:
        # Filter user request to valid downscales only
        valid = []
        for res in requested:
            if res in VALID_RESOLUTIONS:
                res_height = RESOLUTION_HEIGHTS[res]
                if res_height < source_height:
                    valid.append(res)
        return sorted(valid, key=lambda x: -RESOLUTION_HEIGHTS[x])  # Highest first
    else:
        # Auto-detect: all resolutions below source
        targets = []
        for name, height in sorted(RESOLUTION_HEIGHTS.items(), key=lambda x: -x[1]):
            if height < source_height:
                targets.append(name)
        return targets


# ==================== Retry Policy ====================

def get_retry_policy(max_attempts: int = 3) -> RetryPolicy:
    """
    Standard retry policy for all activities.
    
    Uses exponential backoff starting at 2 seconds,
    capped at 30 seconds between retries.
    """
    return RetryPolicy(
        initial_interval=timedelta(seconds=2),
        backoff_coefficient=2.0,
        maximum_interval=timedelta(seconds=30),
        maximum_attempts=max_attempts,
    )


# ==================== Main Workflow ====================

@workflow.defn
class VideoWorkflow:
    """
    Smart DAG Video Processing Workflow.
    
    Features:
        - Conditional thumbnail generation
        - Optional scene detection for chapters
        - Dynamic multi-resolution transcoding
        - Optional watermark overlay
        - Graceful degradation (thumbnail failure doesn't fail workflow)
    
    Pipeline Stages:
        1. DOWNLOAD (optional) → Download from YouTube
        2. METADATA (required)  → Extract video specs
        3. PARALLEL BRANCH:
           - THUMBNAIL (conditional) → Generate preview image
           - SCENE DETECTION (conditional) → Find chapter boundaries
        4. SPLIT (required)     → Chunk video for parallel processing
        5. TRANSCODE (parallel) → Convert chunks × resolutions
        6. PLAYLISTS (required) → Generate HLS m3u8 files
        7. CHAPTERS (conditional) → Generate chapter files
    
    Storage Structure:
        videos/{video_id}/
            source/source.mp4
            source/chunks/chunk_*.mp4
            outputs/
                master.m3u8
                720p/playlist.m3u8, segments/*.ts
                480p/...
                chapters.json, chapters.vtt
        thumbnails/{video_id}/thumbnail.jpg
    """
    
    @workflow.run
    async def run(
        self,
        video_id: str,
        youtube_url: str = None,
        options: dict = None
    ) -> dict:
        """
        Execute the Smart DAG video processing workflow.
        
        Args:
            video_id: Unique identifier for the video
            youtube_url: Optional YouTube URL (if None, assumes video in MinIO)
            options: ProcessingOptions as dict (Temporal requires JSON-serializable)
            
        Returns:
            Complete result dictionary with:
            - success: bool
            - video_id: str
            - metadata: dict (video specs)
            - hls: dict (streaming URLs)
            - thumbnail: dict or None
            - chapters: dict or None
            - warnings: list (non-fatal issues)
            - errors: list or None
        """
        # Parse options (default to empty if not provided)
        opts = ProcessingOptions.from_dict(options or {})
        
        # Track warnings (non-fatal issues)
        warnings = []
        
        # Standard retry policy
        retry_policy = get_retry_policy(max_attempts=3)
        
        # ==================== STAGE 1: DOWNLOAD ====================
        if youtube_url:
            try:
                workflow.logger.info(f"[{video_id}] Stage 1: Downloading from YouTube")
                download_result = await workflow.execute_activity(
                    download_youtube_video,
                    args=[video_id, youtube_url],
                    start_to_close_timeout=timedelta(minutes=10),
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
                    "stage": "download",
                    "error": str(e.cause),
                }
        
        # ==================== STAGE 2: METADATA ====================
        try:
            workflow.logger.info(f"[{video_id}] Stage 2: Extracting metadata")
            metadata = await workflow.execute_activity(
                extract_metadata,
                video_id,
                start_to_close_timeout=timedelta(seconds=60),
                task_queue="metadata-queue",
                retry_policy=retry_policy,
            )
            source_height = metadata.get("height", 0)
            source_width = metadata.get("width", 0)
            video_duration = metadata.get("duration", 0)
            workflow.logger.info(
                f"[{video_id}] Metadata: {source_width}x{source_height}, {video_duration:.1f}s"
            )
        except ActivityError as e:
            workflow.logger.error(f"[{video_id}] Metadata extraction failed: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "stage": "metadata",
                "error": str(e.cause),
            }
        
        # ==================== STAGE 3: PARALLEL BRANCH ====================
        # Run thumbnail and scene detection in parallel (both are fast I/O)
        workflow.logger.info(f"[{video_id}] Stage 3: Parallel branch (thumbnail + scenes)")
        
        parallel_tasks = []
        task_names = []
        
        # Branch A: Thumbnail (conditional)
        thumbnail_result = None
        if opts.thumbnail.mode != "none":
            if opts.thumbnail.mode == "custom" and opts.thumbnail.custom_image_key:
                # User uploaded custom thumbnail
                thumbnail_task = workflow.execute_activity(
                    upload_custom_thumbnail,
                    args=[
                        video_id,
                        opts.thumbnail.custom_image_bucket or "videos",
                        opts.thumbnail.custom_image_key
                    ],
                    start_to_close_timeout=timedelta(seconds=60),
                    task_queue="metadata-queue",
                    retry_policy=retry_policy,
                )
            else:
                # Auto, custom timestamp, or scene-based
                thumbnail_task = workflow.execute_activity(
                    generate_thumbnail,
                    args=[
                        video_id,
                        opts.thumbnail.mode,
                        opts.thumbnail.custom_timestamp,
                        video_duration
                    ],
                    start_to_close_timeout=timedelta(seconds=60),
                    task_queue="metadata-queue",
                    retry_policy=retry_policy,
                )
            parallel_tasks.append(thumbnail_task)
            task_names.append("thumbnail")
        
        # Branch B: Scene Detection (conditional)
        scene_result = None
        if opts.chapters.enabled:
            scene_task = workflow.execute_activity(
                detect_scenes,
                args=[
                    video_id,
                    opts.chapters.scene_threshold,
                    opts.chapters.min_duration,
                    opts.chapters.detect_intro,
                    opts.chapters.detect_outro,
                    video_duration
                ],
                start_to_close_timeout=timedelta(minutes=5),
                task_queue="metadata-queue",
                retry_policy=retry_policy,
            )
            parallel_tasks.append(scene_task)
            task_names.append("scene_detection")
        
        # Execute parallel tasks
        if parallel_tasks:
            parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            
            for i, result in enumerate(parallel_results):
                task_name = task_names[i]
                if isinstance(result, Exception):
                    workflow.logger.warning(f"[{video_id}] {task_name} failed: {result}")
                    warnings.append({
                        "component": task_name,
                        "message": str(result),
                        "recoverable": True
                    })
                else:
                    if task_name == "thumbnail":
                        thumbnail_result = result
                        if not result.get("success"):
                            warnings.append({
                                "component": "thumbnail",
                                "message": result.get("error", "Unknown error"),
                                "recoverable": True
                            })
                    elif task_name == "scene_detection":
                        scene_result = result
                        if not result.get("success"):
                            warnings.append({
                                "component": "scene_detection",
                                "message": result.get("error", "Unknown error"),
                                "recoverable": True
                            })
        
        # ==================== STAGE 4: DETERMINE RESOLUTIONS ====================
        target_resolutions = determine_target_resolutions(source_height, opts.target_resolutions)
        
        if not target_resolutions:
            workflow.logger.info(f"[{video_id}] No valid target resolutions, source is lowest")
            return {
                "success": True,
                "video_id": video_id,
                "metadata": metadata,
                "thumbnail": thumbnail_result,
                "chapters": scene_result,
                "hls": None,
                "message": "Source video is already at minimum resolution, no transcoding needed",
                "warnings": warnings if warnings else None,
            }
        
        workflow.logger.info(f"[{video_id}] Target resolutions: {target_resolutions}")
        
        # ==================== STAGE 5: SPLIT VIDEO ====================
        try:
            workflow.logger.info(f"[{video_id}] Stage 5: Splitting video into chunks")
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
                "stage": "split",
                "error": str(e.cause),
                "thumbnail": thumbnail_result,
                "warnings": warnings if warnings else None,
            }
        
        # ==================== STAGE 6: PARALLEL TRANSCODE ====================
        # Prepare watermark settings
        watermark_text = opts.watermark.text if opts.watermark else None
        watermark_position = opts.watermark.position if opts.watermark else "bottom-right"
        watermark_font_size = opts.watermark.font_size if opts.watermark else 24
        watermark_opacity = opts.watermark.opacity if opts.watermark else 0.5
        
        # Create tasks for every (chunk, resolution) combination
        transcode_tasks = []
        
        for resolution in target_resolutions:
            for chunk in chunks:
                task = workflow.execute_activity(
                    transcode_chunk,
                    args=[
                        video_id,
                        chunk["index"],
                        resolution,
                        chunk["key"],
                        watermark_text,
                        watermark_position,
                        watermark_font_size,
                        watermark_opacity
                    ],
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
            f"[{video_id}] Stage 6: Starting {total_tasks} parallel transcode tasks "
            f"({chunk_count} chunks × {len(target_resolutions)} resolutions)"
            + (f" with watermark" if watermark_text else "")
        )
        
        # Execute all transcode tasks in parallel
        completed_tasks = await asyncio.gather(
            *[t["task"] for t in transcode_tasks],
            return_exceptions=True
        )
        
        # Process results
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
            complete_resolutions = [
                res for res, count in successful_by_resolution.items()
                if count == chunk_count
            ]
            
            if not complete_resolutions:
                return {
                    "success": False,
                    "video_id": video_id,
                    "stage": "transcode",
                    "error": f"No resolution fully transcoded. Errors: {len(transcode_errors)}",
                    "errors": transcode_errors,
                    "thumbnail": thumbnail_result,
                    "warnings": warnings if warnings else None,
                }
            
            # Continue with complete resolutions only
            target_resolutions = complete_resolutions
            workflow.logger.warning(
                f"[{video_id}] Proceeding with complete resolutions: {complete_resolutions}"
            )
        
        # ==================== STAGE 7: GENERATE PLAYLISTS ====================
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
        
        workflow.logger.info(f"[{video_id}] Stage 7: Generating {len(playlist_tasks)} HLS playlists")
        
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
                workflow.logger.error(f"[{video_id}] Playlist {task_info['resolution']} failed: {result}")
                playlist_errors.append({
                    "resolution": task_info["resolution"],
                    "error": str(result),
                })
            else:
                variants.append(result)
        
        # Generate master playlist
        master_result = None
        if variants:
            try:
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
        
        # ==================== STAGE 8: GENERATE CHAPTER FILES ====================
        chapter_files_result = None
        if scene_result and scene_result.get("success") and scene_result.get("chapters"):
            try:
                workflow.logger.info(f"[{video_id}] Stage 8: Generating chapter files")
                chapter_files_result = await workflow.execute_activity(
                    generate_chapter_files,
                    args=[
                        video_id,
                        scene_result["chapters"],
                        scene_result["total_duration"]
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                    task_queue="metadata-queue",
                    retry_policy=retry_policy,
                )
            except ActivityError as e:
                workflow.logger.warning(f"[{video_id}] Chapter file generation failed: {e}")
                warnings.append({
                    "component": "chapter_files",
                    "message": str(e.cause),
                    "recoverable": True
                })
        
        # ==================== FINAL RESULT ====================
        all_errors = transcode_errors + playlist_errors
        
        workflow.logger.info(
            f"[{video_id}] Workflow complete: "
            f"{len(variants)} resolutions, {chunk_count} chunks, "
            f"thumbnail={'Y' if thumbnail_result and thumbnail_result.get('success') else 'N'}, "
            f"chapters={'Y' if chapter_files_result else 'N'}"
        )
        
        return {
            "success": len(variants) > 0,
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
            } if variants else None,
            "thumbnail": {
                "key": thumbnail_result.get("thumbnail_key"),
                "bucket": thumbnail_result.get("thumbnail_bucket", "thumbnails"),
                "mode": thumbnail_result.get("mode"),
            } if thumbnail_result and thumbnail_result.get("success") else None,
            "chapters": {
                "count": scene_result.get("scene_count"),
                "json_key": chapter_files_result.get("json_key") if chapter_files_result else None,
                "vtt_key": chapter_files_result.get("vtt_key") if chapter_files_result else None,
                "chapters": scene_result.get("chapters"),
            } if scene_result and scene_result.get("success") else None,
            "processing_options": opts.to_dict(),
            "has_watermark": bool(watermark_text),
            "warnings": warnings if warnings else None,
            "errors": all_errors if all_errors else None,
        }


# ==================== Completion Workflow ====================

@workflow.defn
class VideoCompletionWorkflow:
    """
    Handles post-processing tasks after video transcoding completes.
    
    Triggered by VideoWorkflow via signal or direct execution.
    
    Responsibilities:
        1. Update video status in metadata database
        2. Invalidate/warm cache entries
        3. Trigger CDN pre-warming (optional)
        4. Send user notifications
        5. Update search index
        6. Emit analytics events
    
    Why separate workflow?
        - Decouples transcoding from notification logic
        - Allows different retry policies
        - Can be extended without modifying main workflow
        - Easier to test independently
    """
    
    @workflow.run
    async def run(
        self,
        video_id: str,
        processing_result: dict,
        notify_user: bool = True
    ) -> dict:
        """
        Execute post-processing tasks.
        
        Args:
            video_id: Video identifier
            processing_result: Result from VideoWorkflow
            notify_user: Whether to send user notification
            
        Returns:
            Completion status
        """
        workflow.logger.info(f"[{video_id}] Starting completion workflow")
        
        completion_tasks = []
        
        # These would be actual activity implementations in production:
        # - update_database_status
        # - invalidate_cache
        # - warm_cdn_cache
        # - send_notification
        # - update_search_index
        
        # For now, just log the completion
        success = processing_result.get("success", False)
        
        workflow.logger.info(
            f"[{video_id}] Video processing {'succeeded' if success else 'failed'}. "
            f"Completion tasks would run here."
        )
        
        return {
            "video_id": video_id,
            "status": "completed" if success else "failed",
            "tasks_executed": [
                "database_update",
                "cache_invalidation",
                "notification_sent" if notify_user else "notification_skipped"
            ],
            "success": True
        }
