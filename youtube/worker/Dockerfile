FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y ffmpeg curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Preserve worker package structure so imports like `worker.activities` resolve
COPY worker/ ./worker/

# Ensure shared package is available for imports
COPY shared/ ./shared/

# Run the workflow worker entrypoint inside the worker package
CMD ["python", "-m", "worker.run_metadata_worker"]