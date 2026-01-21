# Fan-Out Architecture - Quick Start

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Temporal Server                      │
└─────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────▼────┐    ┌──────▼──────┐   ┌─────▼──────┐
   │ video-  │    │  metadata-  │   │ transcode- │
   │  tasks  │    │    queue    │   │   queue    │
   └────┬────┘    └──────┬──────┘   └─────┬──────┘
        │                │                 │
   ┌────▼────┐    ┌─────▼──────┐   ┌─────▼──────┐
   │Workflow │    │  Metadata  │   │ Transcode  │
   │ Worker  │    │   Worker   │   │  Worker    │
   │   (1)   │    │   (10+)    │   │   (2-5)    │
   └─────────┘    └────────────┘   └────────────┘
   
   Orchestrates   Fast & Light    Slow & Heavy
   workflows      I/O bound        CPU bound
```

## ⚡ Quick Start (3 Steps)

### 1. Start Infrastructure
```bash
docker-compose up -d
```

### 2. Start All Workers
```bash
# Set environment
export MINIO_ENDPOINT=http://localhost:9000
export MINIO_ACCESS_KEY=admin
export MINIO_SECRET_KEY=password123

# Activate venv
source youtube-local-venv/bin/activate

# Start all workers at once
./start_workers.sh
```

**Or start individually:**

**Terminal 1: Workflow Worker**
```bash
python worker/run_worker.py
```

**Terminal 2: Metadata Worker**
```bash
python worker/run_metadata_worker.py
```

**Terminal 3: Transcode Worker**
```bash
python worker/run_transcode_worker.py
```

### 3. Test the System
```bash
# Download sample video (optional)
mkdir -p test_videos
curl -o test_videos/sample.mp4 \
  "https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4"

# Run test
python test_video_workflow.py test_videos/sample.mp4
```

## 🔄 Execution Flow

```
1. Client submits workflow
   └─> Temporal schedules on "video-tasks"
   
2. Workflow Worker picks up workflow
   └─> Executes VideoWorkflow.run()
   └─> Schedules extract_metadata on "metadata-queue"
   
3. Metadata Worker picks up activity
   └─> Downloads video from MinIO
   └─> Runs ffprobe
   └─> Returns metadata dict
   
4. Workflow Worker continues
   └─> Receives metadata result
   └─> Schedules transcode_to_720p on "transcode-queue"
   
5. Transcode Worker picks up activity
   └─> Downloads video from MinIO
   └─> Runs ffmpeg transcode
   └─> Uploads to encoded bucket
   └─> Returns result dict
   
6. Workflow Worker completes
   └─> Returns final result to client
```

## 📊 Task Queue Summary

| Queue | Purpose | Worker | Scale | Resource |
|-------|---------|--------|-------|----------|
| `video-tasks` | Workflow orchestration | run_worker.py | 1-2 | Tiny (50MB) |
| `metadata-queue` | Extract metadata | run_metadata_worker.py | 10-50 | Small (200MB) |
| `transcode-queue` | Transcode videos | run_transcode_worker.py | 2-10 | Large (2GB+) |

## 🎯 Benefits of Fan-Out Pattern

### ✅ Independent Scaling
```bash
# Scale metadata workers (cheap)
for i in {1..50}; do python worker/run_metadata_worker.py & done

# Scale transcode workers (expensive)
for i in {1..5}; do python worker/run_transcode_worker.py & done
```

### ✅ Resource Optimization
- **Metadata workers:** Deploy on t3.small (cheap, fast I/O)
- **Transcode workers:** Deploy on c5.2xlarge with GPU (expensive, compute-heavy)

### ✅ Failure Isolation
- If transcode workers crash, metadata extraction continues
- Update workers independently (zero-downtime deploys)

### ✅ Cost Control
- Metadata on spot instances (stateless, can handle interruptions)
- Transcoding on on-demand (long-running, needs completion)

## 🔍 Monitoring

### Watch Logs
```bash
# All workers
tail -f logs/*.log

# Specific worker
tail -f logs/workflow_worker.log
tail -f logs/metadata_worker.log
tail -f logs/transcode_worker.log
```

### Temporal UI
```
http://localhost:8080
```

1. Click "Workflows"
2. Find your workflow: `video-workflow-20260121_...`
3. See activity distribution across queues

### Expected Log Flow

**Workflow Worker:**
```
INFO: Worker started - polling 'video-tasks'...
INFO: Workflow started for video_id
INFO: Metadata extracted: 1920x1080
INFO: Transcode complete: ...720p
```

**Metadata Worker:**
```
INFO: Worker started - polling 'metadata-queue'...
INFO: Extracting metadata for video ID: ...
INFO: Successfully extracted metadata: {...}
```

**Transcode Worker:**
```
INFO: Worker started - polling 'transcode-queue'...
INFO: Starting 720p transcode...
INFO: Running ffmpeg transcode...
INFO: Successfully transcoded: 150MB → 60MB (60% reduction)
```

## 🚀 Scaling Strategies

### Development (1 video at a time)
```
1 Workflow Worker
1 Metadata Worker
1 Transcode Worker
```

### Small Scale (10 videos/hour)
```
1 Workflow Worker
3 Metadata Workers
2 Transcode Workers
```

### Medium Scale (100 videos/hour)
```
2 Workflow Workers
10 Metadata Workers
5 Transcode Workers
```

### Large Scale (1000+ videos/hour)
```
5 Workflow Workers
50 Metadata Workers
20 Transcode Workers (with GPU acceleration)
```

## 🐛 Troubleshooting

### Workflow not starting
```bash
# Check workflow worker
tail -f logs/workflow_worker.log

# Verify task queue
# In test script, ensure: task_queue="video-tasks"
```

### Metadata extraction stuck
```bash
# Check metadata worker running
ps aux | grep run_metadata_worker

# Check logs
tail -f logs/metadata_worker.log

# Check MinIO accessible
curl http://localhost:9000
```

### Transcoding not starting
```bash
# Check transcode worker running
ps aux | grep run_transcode_worker

# Check ffmpeg installed
which ffmpeg

# Check logs
tail -f logs/transcode_worker.log
```

### Activities timeout
```python
# Increase timeout in workflow
start_to_close_timeout=timedelta(minutes=30)  # For large videos
```

## 📁 File Reference

| File | Purpose |
|------|---------|
| `shared/workflows.py` | Workflow definition with task queue routing |
| `worker/activities.py` | Metadata extraction activity |
| `worker/transcode_activities.py` | Transcoding activity |
| `worker/run_worker.py` | Workflow worker (video-tasks) |
| `worker/run_metadata_worker.py` | Metadata worker (metadata-queue) |
| `worker/run_transcode_worker.py` | Transcode worker (transcode-queue) |
| `test_video_workflow.py` | End-to-end test script |
| `start_workers.sh` | Convenience script to start all workers |

## 🎓 Next Steps

1. **Add more queues:** Create priority-queue for premium users
2. **Add more resolutions:** 480p, 1080p, 4K (parallel fan-out)
3. **GPU acceleration:** Use `h264_nvenc` codec on transcode workers
4. **Health checks:** Ping workers, auto-restart on failure
5. **Metrics:** Track queue depth, processing time, success rate

---

**Your video processing system now scales independently by concern! 🚀**
