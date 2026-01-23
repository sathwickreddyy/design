"""
Chunked transcode worker runner.

Purpose: Run workers for split, transcode-chunk, and merge queues.
Consumers: Docker containers or local development.
Logic:
  - Connects to Temporal server
  - Registers split_video, transcode_chunk, merge_segments activities
  - Polls specified queue for tasks
"""
import asyncio
import logging
import sys
import os

from temporalio.client import Client
from temporalio.worker import Worker

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.activities.chunked_transcode import (
    split_video,
    transcode_chunk,
    merge_segments,
    cleanup_source_chunks,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


async def run_split_worker():
    """
    Run worker for split-queue (split_video and cleanup_source_chunks activities).
    
    Split is fast (uses copy codec), so one worker handles both split and cleanup.
    """
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    logger.info(f"Connecting to Temporal at {temporal_host}")
    
    client = await Client.connect(temporal_host)
    
    worker = Worker(
        client,
        task_queue="split-queue",
        activities=[split_video, cleanup_source_chunks],
    )
    
    logger.info("Starting split-queue worker (split_video, cleanup_source_chunks)")
    await worker.run()


async def run_transcode_chunk_worker():
    """
    Run worker for transcode-queue (transcode_chunk activity).
    
    This is CPU-heavy; run multiple instances for parallelism.
    """
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    logger.info(f"Connecting to Temporal at {temporal_host}")
    
    client = await Client.connect(temporal_host)
    
    worker = Worker(
        client,
        task_queue="transcode-queue",
        activities=[transcode_chunk],
    )
    
    logger.info("Starting transcode-queue worker (transcode_chunk)")
    await worker.run()


async def run_merge_worker():
    """
    Run worker for merge-queue (merge_segments activity).
    
    Merge is I/O-heavy (downloads + uploads) but uses copy codec.
    """
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    logger.info(f"Connecting to Temporal at {temporal_host}")
    
    client = await Client.connect(temporal_host)
    
    worker = Worker(
        client,
        task_queue="merge-queue",
        activities=[merge_segments],
    )
    
    logger.info("Starting merge-queue worker (merge_segments)")
    await worker.run()


def main():
    """
    Entry point: run worker based on WORKER_TYPE env var.
    
    WORKER_TYPE options:
      - split: split-queue worker
      - transcode: transcode-queue worker (default)
      - merge: merge-queue worker
      - all: all queues in one worker (dev only)
    """
    worker_type = os.getenv("WORKER_TYPE", "transcode").lower()
    
    if worker_type == "split":
        asyncio.run(run_split_worker())
    elif worker_type == "merge":
        asyncio.run(run_merge_worker())
    elif worker_type == "all":
        # Dev mode: run all activities in one worker
        asyncio.run(run_all_workers())
    else:
        asyncio.run(run_transcode_chunk_worker())


async def run_all_workers():
    """
    Run all chunked transcode activities in one worker (dev/testing only).
    
    In production, use separate workers for each queue for better scaling.
    """
    temporal_host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    logger.info(f"Connecting to Temporal at {temporal_host}")
    
    client = await Client.connect(temporal_host)
    
    # Create workers for each queue
    split_worker = Worker(
        client,
        task_queue="split-queue",
        activities=[split_video, cleanup_source_chunks],
    )
    
    transcode_worker = Worker(
        client,
        task_queue="transcode-queue",
        activities=[transcode_chunk],
    )
    
    merge_worker = Worker(
        client,
        task_queue="merge-queue",
        activities=[merge_segments],
    )
    
    logger.info("Starting all chunked transcode workers (dev mode)")
    
    # Run all workers concurrently
    await asyncio.gather(
        split_worker.run(),
        transcode_worker.run(),
        merge_worker.run(),
    )


if __name__ == "__main__":
    main()
