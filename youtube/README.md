# 🎥 Video Transcoding System - System Design Learning Project

> **Purpose**: A production-grade video transcoding pipeline designed as a learning journey for system design interviews. Each component demonstrates a real-world distributed systems pattern.

## 🎯 What You'll Learn

| Concept | Where It's Used | Interview Relevance |
|---------|-----------------|---------------------|
| **DAG Workflows** | Temporal orchestration | "Design a video processing pipeline" |
| **Queue-based Architecture** | Specialized task queues | "How do you handle backpressure?" |
| **Fan-out/Fan-in** | Parallel chunk transcoding | "How do you scale processing?" |
| **Graceful Degradation** | Optional thumbnail/chapters | "What if a component fails?" |
| **Idempotency** | Deterministic outputs | "How do you handle retries?" |
| **Conditional Processing** | Smart DAG branches | "How do you support different user needs?" |

---

## 📚 Learning Path

### Phase 1: Foundation (Start Here)
1. **[docs/HLS_STREAMING_GUIDE.md](docs/HLS_STREAMING_GUIDE.md)** - Understand HLS format and why we use it
2. **[docs/TRANSCODING_ARCHITECTURE.md](docs/TRANSCODING_ARCHITECTURE.md)** - Basic transcoding concepts

### Phase 2: Scaling Patterns  
3. **[docs/FAN_OUT_ARCHITECTURE.md](docs/FAN_OUT_ARCHITECTURE.md)** - Chunked parallel processing
4. **[docs/VIDEO_SCALING_EXPLAINED.md](docs/VIDEO_SCALING_EXPLAINED.md)** - Why chunks matter for scale

### Phase 3: Advanced Patterns
5. **[docs/SMART_DAG_ARCHITECTURE.md](docs/SMART_DAG_ARCHITECTURE.md)** - Conditional branching and graceful degradation

### Phase 4: Interview Diagrams
6. **[docs/diagrams/](docs/diagrams/)** - D2 diagrams for whiteboard explanations

---

## 🏗 Architecture Overview

```
User Request + Options
        │
        ▼
   ┌─────────┐
   │ FastAPI │ ──▶ Accept request, store video, return immediately
   └────┬────┘
        │
        ▼
   ┌─────────┐
   │Temporal │ ──▶ Orchestrate workflow, manage state, handle retries
   └────┬────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────┐
│                        SMART DAG WORKFLOW                          │
│                                                                    │
│  Download ──▶ Metadata ──┬──▶ Thumbnail (if requested)            │
│                          │                                         │
│                          ├──▶ Scene Detection (if requested)       │
│                          │                                         │
│                          └──▶ Split ──▶ Transcode ──▶ Playlist    │
│                                        (parallel)                  │
│                                        (+ watermark if requested)  │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
   ┌─────────┐
   │  MinIO  │ ──▶ Store original + encoded + thumbnails + chapters
   └─────────┘
        │
        ▼
   HLS Streaming Ready (master.m3u8)
```

---

## 🎛 Processing Options (API Contract)

```python
# POST /videos with ProcessingOptions
{
    "url": "https://youtube.com/watch?v=...",
    "options": {
        # Resolution selection (null = auto from source)
        "resolutions": ["480p", "720p", "1080p"],
        
        # Thumbnail generation
        "thumbnail": {
            "mode": "auto",           # auto | timestamp | scene_based
            "custom_time_seconds": 30  # for timestamp mode
        },
        
        # Watermark overlay
        "watermark": {
            "text": "© MyBrand 2024",
            "position": "bottom_right",
            "font_size": 24
        },
        
        # Chapter generation
        "chapters": {
            "scene_threshold": 0.4,
            "min_scene_length": 5.0
        }
    }
}
```

---

## 🔄 Queue Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            TEMPORAL SERVER                               │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │ video-tasks │    │download-    │    │ metadata-   │                 │
│  │ (workflows) │    │   queue     │    │   queue     │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │ split-queue │    │transcode-   │    │ playlist-   │                 │
│  │             │    │   queue     │    │   queue     │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
└─────────┼──────────────────┼──────────────────┼─────────────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
    ┌───────────┐     ┌───────────┐      ┌───────────┐
    │ 2-3 pods  │     │ 5-50 pods │      │ 1-2 pods  │
    │   Split   │     │ Transcode │      │ Playlist  │
    │  Workers  │     │  Workers  │      │ Workers   │
    └───────────┘     └───────────┘      └───────────┘
                           ↑
                    Heavy compute
                     Auto-scales
```

**Why separate queues?** Different scaling profiles. Transcode is CPU-heavy (scale up), playlist is fast (fixed). Prevents head-of-line blocking.

---

## 🐳 Quick Start

### Prerequisites
- Docker & Docker Compose
- D2 (optional, for diagram generation): `brew install d2`

### Start the Stack

```bash
cd transcoding-engine-stack
docker-compose up -d

# Access:
# - API: http://localhost:8000/docs
# - Temporal UI: http://localhost:8080
# - MinIO Console: http://localhost:9001 (admin/password123)
```

### Upload a Video

```bash
# Basic transcode (all defaults)
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"}'

# With processing options
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "options": {
      "resolutions": ["480p", "720p"],
      "thumbnail": {"mode": "auto"},
      "watermark": {"text": "© Demo", "position": "bottom_right"}
    }
  }'
```

### Check Progress

```bash
# Via API
curl http://localhost:8000/videos/{video_id}/status

# Via Temporal UI
open http://localhost:8080
```

### Play the Stream

```bash
# VLC
vlc "http://localhost:9000/videos/{video_id}/outputs/master.m3u8"

# FFplay
ffplay "http://localhost:9000/videos/{video_id}/outputs/master.m3u8"
```

---

## 📂 Project Structure

```
youtube/
├── main.py                      # FastAPI application
├── shared/
│   ├── workflows.py             # Temporal workflows (Smart DAG)
│   ├── storage.py               # MinIO path helpers
│   └── router.py                # API routes
├── worker/
│   ├── run_worker.py            # Workflow worker
│   ├── run_download_worker.py   # Download activity worker
│   ├── run_metadata_worker.py   # Metadata activity worker
│   ├── run_chunked_worker.py    # Transcode activity worker
│   └── activities/
│       ├── download.py          # YouTube download
│       ├── metadata.py          # FFprobe extraction
│       ├── chunked_transcode.py # FFmpeg transcode + watermark
│       ├── thumbnail.py         # Thumbnail generation
│       └── scene_detection.py   # Scene detection + chapters
├── docs/
│   ├── SMART_DAG_ARCHITECTURE.md
│   ├── HLS_STREAMING_GUIDE.md
│   └── diagrams/                # D2 diagram sources
└── transcoding-engine-stack/
    └── docker-compose.yml       # Full stack deployment
```

---

## 🎯 Interview Talking Points

### "Walk me through the architecture"

> "When a user uploads a video, the API immediately returns and creates a Temporal workflow. The workflow orchestrates activities across specialized queues - download, metadata extraction, chunking, transcoding, and playlist generation. Each queue scales independently based on workload characteristics."

### "How do you handle failures?"

> "We use Temporal for durable execution - workflow state persists across crashes. Activities are idempotent, so retries are safe. We also separate critical path (transcoding) from enhancement path (thumbnails) - thumbnail failures don't block the video."

### "How does it scale?"

> "We use chunked processing - a 2-hour video becomes ~1800 independent 4-second chunks. These process in parallel across N workers. Adding workers linearly increases throughput. The queue acts as a buffer during traffic spikes."

### "Why not just use a single queue?"

> "Different activities have different resource profiles. Transcoding is CPU-heavy (scale to 50 workers), playlist generation is fast (2 workers). Separate queues prevent head-of-line blocking and allow targeted scaling."

---

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal server address |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO/S3 endpoint |
| `MINIO_ACCESS_KEY` | `admin` | MinIO access key |
| `MINIO_SECRET_KEY` | `password123` | MinIO secret key |

### Resolution Presets

| Resolution | Width | Height | Bitrate | Use Case |
|------------|-------|--------|---------|----------|
| `480p` | 854 | 480 | 1M | Mobile, low bandwidth |
| `720p` | 1280 | 720 | 2.5M | Standard HD |
| `1080p` | 1920 | 1080 | 5M | Full HD |

---

## 📊 Generate Architecture Diagrams

```bash
# Generate SVGs from D2 sources
d2 docs/diagrams/01-high-level.d2 docs/diagrams/01-high-level.svg
d2 docs/diagrams/02-design-deep-dive.d2 docs/diagrams/02-design-deep-dive.svg
d2 docs/diagrams/03-final-architecture.d2 docs/diagrams/03-final-architecture.svg

# Open in browser
open docs/diagrams/01-high-level.svg
```

---

## 🛠 Development

### Run Workers Locally (Outside Docker)

```bash
# Create virtual environment
python3 -m venv youtube-local-venv
source youtube-local-venv/bin/activate
pip install -r requirements.txt

# Start workers in separate terminals
python -m worker.run_worker
python -m worker.run_download_worker
python -m worker.run_metadata_worker
python -m worker.run_chunked_worker
```

### Run Tests

```bash
python load_test.py  # Concurrent upload test
```

---

## 📖 Further Reading

- [Temporal Documentation](https://docs.temporal.io/)
- [HLS Specification](https://datatracker.ietf.org/doc/html/rfc8216)
- [FFmpeg Documentation](https://ffmpeg.org/documentation.html)
- [System Design Primer](https://github.com/donnemartin/system-design-primer)

---

## 🎓 Credits

Built as a learning project for system design interviews. Demonstrates real-world patterns used by YouTube, Netflix, and other video platforms.
