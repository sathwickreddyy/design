import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from shared.workflows import VideoWorkflow
from worker.activities import extract_metadata

async def main():
    # Connect to temporal Server
    client = await Client.connect("temporal:7233")

    worker = Worker(
        client,
        task_queue="video-tasks",
        workflows=[VideoWorkflow],
        activities=[extract_metadata],
    )

    print("Worker is starting.... Polling for tasks.")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())