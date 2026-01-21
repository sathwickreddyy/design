from datetime import timedelta
from temporalio import workflow

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities.metadata import extract_metadata
    from worker.activities.transcode import transcode_to_720p


@workflow.defn
class VideoWorkflow:
    @workflow.run
    async def run(self, video_id: str) -> dict:
        """
        Video processing workflow: Extract metadata → Transcode to 720p
        Uses specialized task queues for each activity type
        
        Args:
            video_id: Unique identifier for the video in MinIO
            
        Returns:
            Dictionary with final transcoding results
        """
        # Step 1: Extract metadata on dedicated metadata queue
        # Picked up by lightweight, fast metadata workers
        metadata = await workflow.execute_activity(
            extract_metadata,
            video_id,
            start_to_close_timeout=timedelta(seconds=60),
            task_queue="metadata-queue",  # Fan out to metadata workers
        )
        
        workflow.logger.info(f"Metadata extracted: {metadata.get('width')}x{metadata.get('height')}")
        
        # Step 2: Transcode on dedicated transcode queue
        # Picked up by CPU-heavy transcode workers
        transcode_result = await workflow.execute_activity(
            transcode_to_720p,
            metadata,
            start_to_close_timeout=timedelta(minutes=15),
            task_queue="transcode-queue",  # Fan out to transcode workers
        )
        
        workflow.logger.info(f"Transcode complete: {transcode_result.get('encoded_video_id')}")
        
        return transcode_result