"""
Metadata Worker - Polls for metadata extraction, thumbnail, and scene detection activities
Fast, lightweight I/O operations - scale to many instances
"""
import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

from worker.activities.metadata import extract_metadata
from worker.activities.thumbnail import generate_thumbnail, upload_custom_thumbnail
from worker.activities.scene_detection import detect_scenes, generate_chapter_files

logging.basicConfig(level=logging.INFO)


async def main():
    # Connect to Temporal server (use env var inside container)
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)
    
    # Create worker that handles all metadata-related activities
    # Fast, I/O bound operations - can run many instances
    # NOTE: Does NOT need workflow registration - only executes activities
    worker = Worker(
        client,
        task_queue="metadata-queue",     # Dedicated metadata queue
        activities=[
            # Metadata extraction
            extract_metadata,
            # Thumbnail generation
            generate_thumbnail,
            upload_custom_thumbnail,
            # Scene detection and chapters
            detect_scenes,
            generate_chapter_files,
        ],
        workflows=[],                     # No workflows - activity-only worker
    )
    
    logging.info("Metadata Worker started - polling 'metadata-queue' for metadata, thumbnail, and scene activities...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
