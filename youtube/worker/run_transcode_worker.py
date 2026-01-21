"""
Transcode Worker - Polls for transcoding activities
Run this separately from metadata extraction worker for horizontal scaling
"""
import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

from worker.activities.transcode import transcode_to_720p

logging.basicConfig(level=logging.INFO)


async def main():
    # Connect to Temporal server (use env var inside container)
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)
    
    # Create worker that only handles transcoding activities
    # CPU-heavy, slow operations - scale independently
    # NOTE: Does NOT need workflow registration - only executes activities
    worker = Worker(
        client,
        task_queue="transcode-queue",    # Dedicated transcode queue
        activities=[transcode_to_720p],  # Only transcode activities
        workflows=[],                     # No workflows - activity-only worker
    )
    
    logging.info("Transcode Worker started - polling 'transcode-queue' for transcoding activities...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
