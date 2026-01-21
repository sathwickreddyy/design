"""
Metadata Worker - Polls for metadata extraction activities
Fast, lightweight operations - scale to many instances
"""
import asyncio
import logging
import os
from temporalio.client import Client
from temporalio.worker import Worker

from worker.activities.metadata import extract_metadata

logging.basicConfig(level=logging.INFO)


async def main():
    # Connect to Temporal server (use env var inside container)
    temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(temporal_address)
    
    # Create worker that only handles metadata extraction
    # Fast, I/O bound operations - can run many instances
    # NOTE: Does NOT need workflow registration - only executes activities
    worker = Worker(
        client,
        task_queue="metadata-queue",     # Dedicated metadata queue
        activities=[extract_metadata],   # Only metadata activities
        workflows=[],                     # No workflows - activity-only worker
    )
    
    logging.info("Metadata Worker started - polling 'metadata-queue' for metadata extraction...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
