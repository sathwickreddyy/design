# 🎬 Video Transcoding System - Current State & Future Plans

> **Purpose**: Resume point for future development. Read this to refresh your memory on what was built and what's next.

---

## 📊 CURRENT SYSTEM STATUS (✅ COMPLETE)

### What You Built: Smart DAG Video Transcoding System

A production-grade **VOD (Video on Demand)** transcoding pipeline with conditional workflow orchestration.

#### 🎯 Core Features (All Implemented)
- ✅ **Batch Video Processing**: Upload complete videos, transcode to multiple qualities
- ✅ **HLS Streaming**: Generates adaptive bitrate streams (master.m3u8)
- ✅ **Smart DAG Workflows**: Conditional branching based on user options
- ✅ **Parallel Chunk Processing**: Fan-out transcoding for speed
- ✅ **Enhancement Features**:
  - Thumbnail generation (auto/timestamp/scene-based)
  - Watermark overlay during transcode
  - Scene detection + chapter generation (VTT/JSON/HLS)
  - Custom resolution selection
- ✅ **Graceful Degradation**: Enhancement failures don't block video
- ✅ **Queue-based Architecture**: Separate queues for different workloads

#### 🏗 Technical Stack
- **API**: FastAPI
- **Orchestration**: Temporal (durable workflows)
- **Processing**: FFmpeg (video manipulation)
- **Storage**: MinIO (S3-compatible)
- **Workers**: Python activity workers (specialized by queue)
- **Deployment**: Docker Compose

#### 📂 Project Structure
```
youtube/
├── main.py                      # FastAPI app
├── shared/
│   ├── workflows.py             # VideoWorkflow with Smart DAG
│   ├── storage.py               # MinIO helpers
│   └── router.py                # API routes
├── worker/
│   ├── run_worker.py            # Workflow worker
│   ├── run_download_worker.py   # Download queue
│   ├── run_metadata_worker.py   # Metadata + thumbnail + chapters
│   ├── run_chunked_worker.py    # Transcode queue
│   └── activities/
│       ├── download.py          # YouTube download
│       ├── metadata.py          # FFprobe
│       ├── chunked_transcode.py # Transcode + watermark
│       ├── thumbnail.py         # NEW: Thumbnail generation
│       └── scene_detection.py   # NEW: Scene detection
├── docs/
│   ├── SMART_DAG_ARCHITECTURE.md
│   ├── HLS_STREAMING_GUIDE.md
│   ├── TRANSCODING_ARCHITECTURE.md
│   └── diagrams/
│       ├── 01-high-level.d2/.svg
│       ├── 02-design-deep-dive.d2/.svg
│       ├── 03-final-architecture.d2/.svg
│       ├── flow-01-basic.d2/.svg
│       ├── flow-02-thumbnail.d2/.svg
│       └── ... (7 flow scenarios)
└── transcoding-engine-stack/
    └── docker-compose.yml       # Full stack
```

#### 🔄 How It Works (VOD Pipeline)
```
1. User uploads complete video file
2. API creates Temporal workflow
3. Workflow orchestrates activities across queues:
   - Download video
   - Extract metadata
   - Generate thumbnail (optional)
   - Detect scenes + create chapters (optional)
   - Split into chunks
   - Transcode chunks (parallel, with watermark if requested)
   - Generate HLS playlists
4. Video available for streaming
5. Completion workflow updates DB/cache
```

#### 🎮 API Usage
```bash
# Basic transcode
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=..."}'

# With all features
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "resolutions": ["1080p", "720p"],
      "thumbnail": {"mode": "auto"},
      "watermark": {"text": "© Brand", "position": "bottom_right"},
      "chapters": {"scene_threshold": 0.4}
    }
  }'
```

#### 📈 What You Learned
- DAG workflows with Temporal
- Fan-out/fan-in parallel processing
- Queue-based architecture for scaling
- Graceful degradation patterns
- HLS streaming format
- FFmpeg video processing
- Conditional workflow branching

---

## 🚀 FUTURE ENHANCEMENT: LIVE STREAMING (📋 PLANNED)

### What's Next: Add Real-Time Live Streaming

Transform the system to support **LIVE streaming** (like Twitch/YouTube Live) in addition to VOD.

#### 🎯 Goal
Enable users to:
1. Stream live from camera/OBS
2. Transcode in real-time (< 4s per segment)
3. Viewers watch with ~10-15s delay
4. Optionally save stream as VOD after

#### 🔄 Key Differences from VOD

| Aspect | VOD (Current) | Live Streaming (New) |
|--------|---------------|----------------------|
| Input | Complete file | Continuous stream |
| Protocol | HTTP POST | RTMP/WebRTC |
| Processing | Batch (parallel) | Real-time (serial) |
| Storage | Permanent | Temporary (30s window) |
| Playlist | Static | Dynamic (updates every 4s) |
| Workers | Stateless | Stateful per stream |
| Constraint | Quality | Speed (must finish < 4s) |

#### 🧩 New Components Needed

1. **RTMP Ingest Server** (NEW)
   - Accept live streams from OBS/encoder
   - Technology: nginx-rtmp-module or Wowza
   - Port: 1935 (RTMP)

2. **Live Transcoder** (Modified)
   - Real-time processing constraints
   - FFmpeg preset: "ultrafast" + "zerolatency"
   - Must process segment in < segment duration

3. **Origin Server** (NEW)
   - Generate dynamic HLS playlists
   - Update every 4 seconds
   - No #EXT-X-ENDLIST tag (still streaming)

4. **Stream State Manager** (NEW)
   - Redis or PostgreSQL
   - Track active streams, viewers, health

5. **Stream Recorder** (Optional)
   - Save live stream to storage
   - After stream ends, becomes VOD
   - Reuses existing VOD pipeline

#### 📁 Documentation Already Prepared

Located in: `future-enhancements/live-streaming/`

- **LIVE_STREAMING_DESIGN_THINKING.md**: Complete mental model and design framework
- **LIVE_STREAMING_GUIDE.md**: Quick reference and interview prep
- **Diagrams**:
  - `live-01-vod-vs-live.svg`: Architecture comparison
  - `live-02-complete-architecture.svg`: Full live system
  - `live-03-timeline-flow.svg`: Real-time processing timeline
  - `live-04-hybrid-system.svg`: How to add to current system
  - `live-05-failure-scenarios.svg`: Failure modes & recovery

#### 🛠 Implementation Phases (Estimated 6-8 weeks)

**Phase 1: Ingest Server (Week 1-2)**
```
- Deploy nginx-rtmp in Docker
- Configure RTMP endpoint (port 1935)
- Add stream key authentication
- Test with OBS Studio
```

**Phase 2: Live Transcoder (Week 3-4)**
```
- Create new worker: run_live_worker.py
- Implement live_transcode_segment activity
- Use real-time FFmpeg presets
- Add buffer monitoring
- Handle backpressure (drop frames if slow)
```

**Phase 3: Origin Server (Week 5-6)**
```
- Build origin service (FastAPI)
- Dynamic HLS playlist generation
- Redis for segment metadata
- Segment cleanup (delete after 30s)
- API routes: /live/start, /live/stop
```

**Phase 4: Integration & Testing (Week 7-8)**
```
- Connect all components
- Add stream state management
- Implement optional recording
- CDN integration
- Load testing
```

---

## 🎓 WHY THIS ARCHITECTURE?

### Design Decisions Explained

#### VOD: Batch Processing
```
Why: Complete file available → Optimize for quality
Pattern: Fan-out parallel processing
Scale: Worker count
Cost: Per video processed
```

#### Live: Stream Processing
```
Why: Continuous data → Optimize for speed
Pattern: Serial real-time processing
Scale: Per stream capacity
Cost: Per minute streaming
```

#### Temporal for Orchestration
```
Why: Durable execution, built-in retries, workflow versioning
Handles: State persistence, activity timeouts, failure recovery
Alternative: Kafka + custom state management (more complex)
```

#### Queue Separation
```
Why: Different workloads have different resource needs
Example:
- download-queue: I/O bound (2-5 workers)
- transcode-queue: CPU bound (5-50 workers, auto-scale)
- playlist-queue: Fast (1-2 workers)

Prevents: Head-of-line blocking
```

#### Graceful Degradation
```
Why: Enhancement failures shouldn't block core video
Pattern: Try/except on optional features
Result: Video works even if thumbnail fails
```

---

## 📖 LEARNING RESOURCES

### Understanding the Current System
1. Read: `docs/SMART_DAG_ARCHITECTURE.md` (main architecture doc)
2. View: `docs/diagrams/flow-05-all-features.svg` (complete flow)
3. Code: `shared/workflows.py` (VideoWorkflow implementation)

### Understanding Live Streaming
1. Read: `future-enhancements/live-streaming/LIVE_STREAMING_DESIGN_THINKING.md`
2. View: All diagrams in `future-enhancements/live-streaming/`
3. Compare: VOD vs Live differences

### Interview Prep
- Current system: Use flow diagrams to explain Smart DAG
- Live streaming: Use `live-04-hybrid-system.svg` to explain extension
- Scaling: Discuss queue architecture and worker scaling

---

## 🔍 QUICK VERIFICATION (Test Current System)

```bash
# 1. Start the stack
cd transcoding-engine-stack
docker-compose up -d

# 2. Upload a test video
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}'

# 3. Watch progress in Temporal UI
open http://localhost:8080

# 4. Play the result
# Get video_id from API response, then:
vlc "http://localhost:9000/videos/{video_id}/outputs/master.m3u8"

# 5. Check features
# - Thumbnail: http://localhost:9001 (MinIO Console)
#   → thumbnails bucket → {video_id}/thumbnail.jpg
# - Chapters: http://localhost:9000/videos/{video_id}/chapters/chapters.vtt
```

---

## 🎯 KEY FILES TO UNDERSTAND

### Core Workflow Logic
- `shared/workflows.py` - **START HERE**: VideoWorkflow with Smart DAG
- `shared/storage.py` - MinIO path helpers

### Activities (What Workers Do)
- `worker/activities/download.py` - YouTube download
- `worker/activities/metadata.py` - FFprobe extraction
- `worker/activities/thumbnail.py` - Thumbnail generation
- `worker/activities/scene_detection.py` - Scene detection + chapters
- `worker/activities/chunked_transcode.py` - Transcode + watermark

### Worker Registration
- `worker/run_worker.py` - Workflow orchestration
- `worker/run_metadata_worker.py` - Metadata/thumbnail/chapters
- `worker/run_chunked_worker.py` - Heavy transcode work

### Configuration
- `transcoding-engine-stack/docker-compose.yml` - Full stack definition

---

## 💡 IMPORTANT NOTES

### Before Starting Live Streaming Implementation

1. **Current system is production-ready for VOD**
   - All features work
   - Well-documented
   - Can be used as-is

2. **Live streaming is a separate concern**
   - Don't modify existing VOD code
   - Build alongside as new services
   - Share storage/CDN infrastructure

3. **Read the design thinking doc first**
   - Understand mental model shift
   - Learn why components are needed
   - See failure scenarios

4. **Start with proof of concept**
   - nginx-rtmp on local machine
   - OBS → Ingest → FFmpeg → HLS
   - Test before integrating with Temporal

### Cost Implications
```
VOD: $X per video (one-time)
Live: $Y per minute (continuous)

Example:
- 1 hour VOD processing: $0.50-1.00
- 1 hour live streaming: $5-10
- 1000 concurrent viewers: +$50-100/hour
```

---

## 🚦 RESUMING THIS PROJECT

### Immediate Next Steps When You Return:

1. **Refresh Memory** (15 minutes)
   ```
   - Read this file (you're here!)
   - View: docs/diagrams/03-final-architecture.svg
   - View: future-enhancements/live-streaming/live-04-hybrid-system.svg
   ```

2. **Test Current System** (15 minutes)
   ```
   - Start Docker stack
   - Upload a video with all options
   - Verify it works
   ```

3. **Read Live Streaming Docs** (1 hour)
   ```
   - LIVE_STREAMING_DESIGN_THINKING.md (mental model)
   - LIVE_STREAMING_GUIDE.md (implementation guide)
   - View all 5 diagrams
   ```

4. **Start Implementation** (Week 1)
   ```
   - Follow Phase 1: Deploy nginx-rtmp
   - See: future-enhancements/live-streaming/LIVE_STREAMING_GUIDE.md
   ```

---

## 📞 GETTING HELP

When asking GPT/Claude for help:

1. **Provide context**: "I built a VOD transcoding system with Temporal + FFmpeg. Now adding live streaming."

2. **Share this file**: "Here's my PROJECT_CONTEXT.md..."

3. **Be specific**: 
   - "How do I configure nginx-rtmp for RTMP ingest?"
   - "How to implement real-time transcoding with FFmpeg?"
   - "How to generate dynamic HLS playlists?"

4. **Reference diagrams**: "See live-02-complete-architecture.svg for what I'm building"

---

## ✨ SUMMARY

**You Have**: Production-grade VOD system with Smart DAG workflows ✅

**You're Building**: Real-time live streaming capability 🚧

**Location**: All live streaming materials in `future-enhancements/live-streaming/`

**Next Action**: Read the live streaming design docs, then start with nginx-rtmp proof of concept

**Time Estimate**: 6-8 weeks for full implementation

**Learning Value**: Understand batch vs stream processing, real-time constraints, stateful systems

Good luck! 🚀
