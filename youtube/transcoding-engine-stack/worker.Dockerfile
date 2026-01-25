FROM python:3.13-slim

WORKDIR /app

# Install ffmpeg for video processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY worker/ ./worker/

# Default command (override in docker-compose)
CMD ["python", "-m", "worker.run_worker"]
