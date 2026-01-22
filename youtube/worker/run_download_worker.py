"""
Download worker for YouTube video downloads.

Purpose: Poll 'download-queue' and execute YouTube download activities.
Consumers: Temporal server dispatches download tasks to these workers.
Logic:
  1. Connect to Temporal server
  2. Register download_youtube_video activity
  3. Poll download-queue for tasks
  4. Execute downloads with rate limiting via worker count
"""
import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker
from worker.activities.download import download_youtube_video

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """
    Start the download worker.
    
    Logic:
        1. Get Temporal server address from environment
        2. Connect to Temporal client
        3. Create worker polling 'download-queue'
        4. Register download activity
        5. Start worker (blocks until shutdown)
    """
    # Get Temporal address from environment
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    logger.info(f"Connecting to Temporal at {temporal_address}")
    
    # Connect to Temporal
    client = await Client.connect(temporal_address)
    
    # Create and run worker
    worker = Worker(
        client,
        task_queue="download-queue",
        activities=[download_youtube_video],
    )
    
    logger.info("Download Worker started - polling 'download-queue' for YouTube download activities...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
