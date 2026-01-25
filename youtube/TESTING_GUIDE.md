# 🧪 Manual Testing Guide

## Quick Start: Test Video Upload

### 1. Start the Stack

```bash
cd transcoding-engine-stack
docker-compose up -d

# Wait ~30 seconds for services to initialize
docker-compose ps  # All services should be "running"
```

### 2. Upload a Test Video

**Option A: Upload from YouTube URL**

```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  }'

# Response:
# {
#   "workflow_id": "workflow-20260125_143022_a1b2c3d4",
#   "video_id": "20260125_143022_a1b2c3d4",
#   "status": "started"
# }
```

**Option B: Upload Local Video File**

```bash
# First, upload file to MinIO
curl -X POST "http://localhost:8000/upload-file" \
  -F "file=@/path/to/your/video.mp4"

# Response includes video_id:
# {
#   "video_id": "20260125_143022_a1b2c3d4",
#   "workflow_id": "workflow-20260125_143022_a1b2c3d4"
# }
```

### 3. Monitor Progress

**Check Workflow Status:**

```bash
WORKFLOW_ID="workflow-20260125_143022_a1b2c3d4"

curl "http://localhost:8000/status/$WORKFLOW_ID"
```

**Watch Temporal UI:**

1. Open http://localhost:8080
2. Click on your workflow
3. Watch activities execute in real-time
4. See parallel transcode tasks spawn

**Watch Logs:**

```bash
# All workers
docker-compose logs -f

# Just transcode workers
docker-compose logs -f youtube-chunk-transcode-worker

# Just playlist worker
docker-compose logs -f youtube-playlist-worker
```

### 4. Access the HLS Stream

Once workflow completes, get the video_id and play:

**Using VLC:**

```bash
VIDEO_ID="20260125_143022_a1b2c3d4"

vlc "http://localhost:9000/videos/$VIDEO_ID/outputs/master.m3u8"
```

**Using ffplay:**

```bash
ffplay "http://localhost:9000/videos/$VIDEO_ID/outputs/master.m3u8"
```

**Browse in MinIO Console:**

1. Open http://localhost:9001
2. Login: admin / password123
3. Navigate to `videos` bucket
4. Browse to `{video_id}/outputs/`
5. You'll see:
   - `master.m3u8` (master playlist)
   - `720p/playlist.m3u8` (variant playlist)
   - `720p/segments/seg_*.ts` (video chunks)

---

## Detailed Testing Scenarios

### Test 1: Small Video (Quick Test)

```bash
# Use a short YouTube video (1-2 minutes)
curl -X POST "http://localhost:8000/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"
  }'

# Expected time: ~2-3 minutes
# - Download: 10-20 seconds
# - Metadata: 5 seconds
# - Split: 5 seconds
# - Transcode: 1-2 minutes
# - Playlist: instant
```

### Test 2: Resolution Downscaling Logic

**Test with 4K video (should generate 1080p, 720p, 480p, 320p):**

```bash
curl -X POST "http://localhost:8000/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=LXb3EKWsInQ"
  }'

# Check result - should have 4 variants
```

**Test with 480p video (should only generate 320p):**

```bash
# Upload a 480p source
# Workflow should skip 720p and 1080p
```

### Test 3: Parallel Execution

Monitor during transcoding to see parallelism:

```bash
# In one terminal
docker stats youtube-chunk-transcode-worker

# You should see CPU spike to 100% per container
# With 4 replicas, all 4 should show high CPU
```

### Test 4: Failure Recovery

**Kill a transcode worker mid-processing:**

```bash
# Start a workflow
curl -X POST "http://localhost:8000/upload" ...

# Kill one worker
docker kill youtube-chunk-transcode-worker-1

# Workflow should continue with remaining workers
# Temporal will retry failed chunks on other workers
```

---

## Verify Output Structure

```bash
VIDEO_ID="20260125_143022_a1b2c3d4"

# List all files in MinIO
docker exec youtube-minio-storage-server \
  mc ls minio/videos/$VIDEO_ID/outputs/ --recursive

# Expected output:
# outputs/master.m3u8
# outputs/720p/playlist.m3u8
# outputs/720p/segments/seg_0000.ts
# outputs/720p/segments/seg_0001.ts
# ...
# outputs/480p/playlist.m3u8
# outputs/480p/segments/...
```

---

## Performance Benchmarks

| Video Length | Source | Resolutions | Chunks | Processing Time |
|--------------|--------|-------------|--------|-----------------|
| 1 min | 1080p | 3 (720p,480p,320p) | 15 | ~2 min |
| 5 min | 1080p | 3 | 75 | ~6 min |
| 30 min | 1080p | 3 | 450 | ~25 min |
| 60 min | 4K | 4 (1080p,720p,480p,320p) | 900 | ~50 min |

*With 4 transcode worker replicas*

---

## Troubleshooting

### "Connection refused to Temporal"

```bash
# Check Temporal is running
docker-compose ps temporal

# If not healthy, restart
docker-compose restart temporal
```

### "MinIO bucket not found"

```bash
# Workers auto-create buckets, but you can manually create:
docker exec youtube-minio-storage-server \
  mc mb minio/videos
```

### "No workers polling queue"

```bash
# Check worker logs
docker-compose logs youtube-playlist-worker

# Restart workers
docker-compose restart youtube-playlist-worker
```

### "ffmpeg not found"

```bash
# Rebuild worker images
docker-compose build youtube-chunk-transcode-worker
docker-compose up -d
```

---

## Clean Up

```bash
# Stop all services
docker-compose down

# Remove volumes (deletes all videos!)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```
