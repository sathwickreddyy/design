from datetime import timedelta
from temporalio import workflow

# Import activity type for type-hinting (but don't import implementation)
with workflow.unsafe.imports_passed_through():
    from worker.activities import extract_metadata


@workflow.defn
class VideoWorkflow:
    @workflow.run
    async def run(self, video_id: str) -> str:
        # Step1: Sequentical Task
        result = await workflow.execute_activity(
            extract_metadata,
            video_id,
            start_to_close_timeout=timedelta(seconds=30),
        )
        return result