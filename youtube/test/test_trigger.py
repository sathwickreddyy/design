import asyncio
from temporalio.client import Client
from shared.workflows import VideoWorkflow

async def main():
    client = await Client.connect("localhost:7233")
    result = await client.execute_workflow(
        VideoWorkflow.run, "test-video-123", 
        id="video-123", task_queue="video-tasks"
    )
    print(f"Workflow Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())