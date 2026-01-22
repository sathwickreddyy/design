"""
Transcode Worker - Polls for transcoding activities.

Purpose: Execute CPU-heavy video transcoding tasks.
Consumers: Temporal server dispatches transcode tasks to these workers.
Logic:
  1. Connect to Temporal server
  2. Register ALL transcode activities (320p, 480p, 720p, 1080p)
  3. Poll transcode-queue for tasks
  4. Execute appropriate activity based on task metadata
"""
import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

from worker.activities.transcode import (
    transcode_to_320p,
    transcode_to_480p,
    transcode_to_720p,
    transcode_to_1080p,
)

logging.basicConfig(level=logging.INFO)


async def main():
    """
    Start the transcode worker.
    
    Logic:
        1. Get Temporal server address from environment
        2. Connect to Temporal client
        3. Create worker with ALL transcode activities registered
        4. Poll transcode-queue (blocks until shutdown)
    """
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)
    
    # Register ALL transcode activities
    # Worker will execute whichever activity the task specifies
    worker = Worker(
        client,
        task_queue="transcode-queue",
        activities=[
            transcode_to_320p,
            transcode_to_480p,
            transcode_to_720p,
            transcode_to_1080p,
        ],
        workflows=[],
    )
    
    logging.info("Transcode Worker started - polling 'transcode-queue' for 320p/480p/720p/1080p activities...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
