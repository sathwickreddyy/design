#!/bin/bash
# Start all workers for the fan-out architecture

echo "🚀 Starting Video Processing Workers"
echo "===================================="
echo ""

# Check if virtual environment is activated
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠️  Virtual environment not activated!"
    echo "Run: source youtube-local-venv/bin/activate"
    exit 1
fi

# Check environment variables
if [[ -z "$MINIO_ENDPOINT" ]]; then
    echo "⚠️  MINIO_ENDPOINT not set!"
    echo "Run: export MINIO_ENDPOINT=http://localhost:9000"
    exit 1
fi

echo "✅ Environment configured"
echo ""

# Start workers in background with process names
echo "Starting workers..."
echo ""

# 1. Workflow Worker (Orchestration)
echo "📋 Starting Workflow Worker (video-tasks)..."
python worker/run_worker.py > logs/workflow_worker.log 2>&1 &
WORKFLOW_PID=$!
echo "   PID: $WORKFLOW_PID"

sleep 2

# 2. Metadata Workers (Fast, can start many)
echo "🔍 Starting Metadata Worker (metadata-queue)..."
python worker/run_metadata_worker.py > logs/metadata_worker.log 2>&1 &
METADATA_PID=$!
echo "   PID: $METADATA_PID"

sleep 2

# 3. Transcode Workers (Slow, CPU-heavy)
echo "🎬 Starting Transcode Worker (transcode-queue)..."
python worker/run_transcode_worker.py > logs/transcode_worker.log 2>&1 &
TRANSCODE_PID=$!
echo "   PID: $TRANSCODE_PID"

sleep 2

echo ""
echo "✅ All workers started!"
echo ""
echo "Worker PIDs:"
echo "  Workflow:  $WORKFLOW_PID"
echo "  Metadata:  $METADATA_PID"
echo "  Transcode: $TRANSCODE_PID"
echo ""
echo "Logs:"
echo "  tail -f logs/workflow_worker.log"
echo "  tail -f logs/metadata_worker.log"
echo "  tail -f logs/transcode_worker.log"
echo ""
echo "To stop all workers:"
echo "  kill $WORKFLOW_PID $METADATA_PID $TRANSCODE_PID"
echo ""
echo "Or save PIDs to file:"
echo "  echo \"$WORKFLOW_PID $METADATA_PID $TRANSCODE_PID\" > .worker_pids"
