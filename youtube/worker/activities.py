from temporalio import activity


async def extract_metadata(video_id: str) -> str:
    activity.logger.info(f"Extracting metadata for video ID: {video_id}")
    # Simulate metadata extraction logic
    return f"Successfully extracted metadata for video ID: {video_id}"