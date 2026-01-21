import asyncio
import logging
from temporalio.client import Client
from temporalio.worker import Worker
from shared.workflows import VideoWorkflow

logging.basicConfig(level=logging.INFO)

async def main():
    # Connect to temporal Server
    client = await Client.connect("localhost:7233")

    # Workflow-only worker: Orchestrates the workflow logic
    # Does NOT execute activities - just coordinates them
    worker = Worker(
        client,
        task_queue="video-tasks",  # Workflow execution queue
        workflows=[VideoWorkflow],
        activities=[],  # No activities - just workflow orchestration
    )

    logging.info("Workflow Worker started - polling 'video-tasks' for workflow execution...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())