from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities.download import download_youtube_video
    from worker.activities.metadata import extract_metadata
    from worker.activities.transcode import transcode_to_720p


@workflow.defn
class VideoWorkflow:
    @workflow.run
    async def run(self, video_id: str, youtube_url: str = None) -> dict:
        """
        Video processing workflow: Download (if YouTube) → Extract metadata → Transcode to 720p
        Uses specialized task queues for each activity type
        
        Args:
            video_id: Unique identifier for the video in MinIO
            youtube_url: Optional YouTube URL for download (if None, assumes video already in MinIO)
            
        Returns:
            Dictionary with final transcoding results or error details
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
                workflow.logger.info(f"Starting YouTube download for {video_id}")
                download_result = await workflow.execute_activity(
                    download_youtube_video,
                    args=[video_id, youtube_url],
                    start_to_close_timeout=timedelta(minutes=5),
                    task_queue="download-queue",  # Fan out to download workers
                    retry_policy=retry_policy,
                )
                workflow.logger.info(f"Download complete: {download_result.get('title')} ({download_result.get('file_size_bytes', 0) / 1024 / 1024:.2f} MB)")
            except ActivityError as e:
                workflow.logger.error(f"Failed to download YouTube video after {retry_policy.maximum_attempts} attempts: {e}")
                return {
                    "success": False,
                    "video_id": video_id,
                    "error": "download_failed",
                    "message": f"Failed to download YouTube video after maximum retries: {str(e.cause)}",
                }
        
        try:
            # Step 2: Extract metadata on dedicated metadata queue
            # Picked up by lightweight, fast metadata workers
            metadata = await workflow.execute_activity(
                extract_metadata,
                video_id,
                start_to_close_timeout=timedelta(seconds=60),
                task_queue="metadata-queue",  # Fan out to metadata workers
                retry_policy=retry_policy,
            )
            
            workflow.logger.info(f"Metadata extracted: {metadata.get('width')}x{metadata.get('height')}")
            
        except ActivityError as e:
            workflow.logger.error(f"Failed to extract metadata after {retry_policy.maximum_attempts} attempts: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "error": "metadata_extraction_failed",
                "message": f"Failed to extract metadata after maximum retries: {str(e.cause)}",
            }
        
        try:
            # Step 2: Transcode on dedicated transcode queue
            # Picked up by CPU-heavy transcode workers
            transcode_result = await workflow.execute_activity(
                transcode_to_720p,
                metadata,
                start_to_close_timeout=timedelta(minutes=15),
                task_queue="transcode-queue",  # Fan out to transcode workers
                retry_policy=retry_policy,
            )
            
            workflow.logger.info(f"Transcode complete: {transcode_result.get('encoded_video_id')}")
            
            return transcode_result
            
        except ActivityError as e:
            workflow.logger.error(f"Failed to transcode after {retry_policy.maximum_attempts} attempts: {e}")
            return {
                "success": False,
                "video_id": video_id,
                "metadata": metadata,
                "error": "transcoding_failed",
                "message": f"Failed to transcode after maximum retries: {str(e.cause)}",
            }