# Video Transcoding Architecture

## 🎯 Overview

Multi-step video processing workflow with HLS streaming output:
1. **Extract Metadata** → Get video specs (resolution, duration, codecs)
2. **Split Video** → GOP-aligned chunks for parallel processing
3. **Transcode Chunks** → Convert each chunk to multiple resolutions (.ts)
4. **Generate Playlists** → Create HLS m3u8 files for adaptive streaming

## 📁 File Structure

```
worker/
├── activities/
│   ├── download.py              # YouTube download activity
│   ├── metadata.py              # Metadata extraction (fast)
│   └── chunked_transcode.py     # Split, transcode, HLS playlist
├── run_worker.py                # Combined worker
└── run_chunked_worker.py        # Dedicated transcode worker

shared/
├── workflows.py                 # Workflow definition (HLS output)
└── storage.py                   # MinIO operations + HLS paths

docs/
├── VIDEO_SCALING_EXPLAINED.md   # Deep dive into scaling algorithms
└── TRANSCODING_ARCHITECTURE.md  # This file
```

## 🔄 How It Works

### Workflow Chain (HLS Output)
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Upload      │     │ Extract      │     │ Split       │
│ Video       │  →  │ Metadata     │  →  │ into Chunks │
│ (raw)       │     │ (5-10 sec)   │     │ (instant)   │
└─────────────┘     └──────────────┘     └─────────────┘
     │                    │                    │
     ▼                    ▼                    ▼
source.mp4        {width: 1920,         chunk_0.mp4
                   height: 1080,        chunk_1.mp4
                   codec: h264...}      chunk_N.mp4
                                              │
                                              ▼
┌────────────────────────────────────────────────────────────┐
│           Parallel Transcode (N chunks × M resolutions)        │
│  chunk_0 → [720p.ts, 480p.ts, 320p.ts]                         │
│  chunk_1 → [720p.ts, 480p.ts, 320p.ts]                         │
│  chunk_N → [720p.ts, 480p.ts, 320p.ts]                         │
└────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────┐
│                Generate HLS Playlists (instant)                │
│  720p/playlist.m3u8 → references seg_0000.ts ... seg_N.ts     │
│  480p/playlist.m3u8 → references seg_0000.ts ... seg_N.ts     │
│  320p/playlist.m3u8 → references seg_0000.ts ... seg_N.ts     │
│  master.m3u8        → lists all quality levels                 │
└────────────────────────────────────────────────────────────┘
```

### Data Flow
```python
# Input to workflow
video_id = "20260121_143022_a1b2c3d4"

# Step 1: Extract metadata
metadata = {
    "video_id": "20260121_143022_a1b2c3d4",
    "width": 1920,
    "height": 1080,
    "duration": 125.5,
    "codec": "h264"
}

# Step 2: Split into chunks
split_result = {
    "chunk_count": 32,
    "chunks": [{"index": 0, "key": "..."}, ...]
}

# Step 3: Parallel transcode (generates .ts segments)
# 32 chunks × 3 resolutions = 96 parallel tasks!

# Step 4: Generate HLS playlists (instant - just text files)
result = {
    "success": True,
    "video_id": "20260121_143022_a1b2c3d4",
    "metadata": metadata,
    "source_resolution": "1920x1080",
    "chunk_count": 32,
    "hls": {
        "master_playlist": "{video_id}/outputs/master.m3u8",
        "variants": [
            {"resolution": "720p", "playlist": "...", "bandwidth": 2800000},
            {"resolution": "480p", "playlist": "...", "bandwidth": 1400000},
            {"resolution": "320p", "playlist": "...", "bandwidth": 800000},
        ]
    }
}
```

## 🚀 Running Workers

### Option 1: Single Worker (Both Activities)
**Use case:** Development, small scale

```bash
# From project root
python worker/run_worker.py
```

**Handles:**
- `extract_metadata` (fast)
- `transcode_to_720p` (slow)

**⚠️ Problem:** Fast activities blocked by slow transcoding

---

### Option 2: Separate Workers (Recommended)
**Use case:** Production, horizontal scaling

**Terminal 1: Metadata Worker**
```bash
python worker/run_worker.py
```

**Terminal 2: Transcode Worker**
```bash
python worker/run_transcode_worker.py
```

**Terminal 3: Another Transcode Worker (scale out!)**
```bash
python worker/run_transcode_worker.py
```

**Benefits:**
- Metadata extraction never blocked
- Scale transcode workers independently
- Utilize multiple CPU cores

---

## 🎬 Transcode Activity Details

### Input
```python
metadata = {
    "video_id": "20260121_143022_a1b2c3d4",
    "width": 1920,
    "height": 1080,
    # ... other metadata
}
```

### Process
1. Download from `videos/video_id`
2. Run ffmpeg:
   ```bash
   ffmpeg -i input.mp4 \
     -vf "scale=-2:720" \
     -c:v libx264 -preset medium -crf 23 \
     -c:a aac -b:a 128k \
     -progress pipe:1 \
     output_720p.mp4
   ```
3. Upload to `encoded/video_id_720p`
4. Cleanup temp files

### ffmpeg Parameters Explained
| Parameter | Value | Why? |
|-----------|-------|------|
| `scale=-2:720` | Auto-width, 720p height | Maintains 16:9, ensures even dimensions |
| `-c:v libx264` | H.264 codec | Universal compatibility |
| `-preset medium` | Encoding speed | Balanced speed vs quality |
| `-crf 23` | Quality factor | Excellent quality, reasonable size |
| `-c:a aac` | Audio codec | Standard web audio |
| `-b:a 128k` | Audio bitrate | Good quality stereo |
| `-progress pipe:1` | Progress to stdout | Real-time monitoring |

### Output
```python
{
    "video_id": "20260121_143022_a1b2c3d4",
    "encoded_video_id": "20260121_143022_a1b2c3d4_720p",
    "original_resolution": "1920x1080",
    "target_resolution": "1280x720",
    "input_file_size": 157286400,   # 150 MB
    "output_file_size": 62914560,   # 60 MB
    "compression_ratio": "60.0%",
    "success": true
}
```

---

## 📊 Performance Expectations

### Metadata Extraction
- **Duration:** 5-10 seconds
- **CPU:** Low (file header reading)
- **Memory:** ~50 MB
- **Parallelism:** High (I/O bound)

### Transcoding (720p)
- **Duration:** Depends on video length
  - 1 min video → ~30 seconds
  - 10 min video → ~5 minutes
  - 60 min video → ~30 minutes
- **CPU:** High (100% of 1-2 cores)
- **Memory:** 200-500 MB
- **Parallelism:** Limited (CPU bound)

**Rule of thumb:** Transcoding takes ~50% of video duration with `-preset medium`

---

## 🔍 Monitoring Progress

The `-progress pipe:1` flag outputs real-time stats:

```
frame=150              # 150 frames processed
fps=30.5               # Processing 30.5 frames/sec
time=00:00:05.00       # At 5 seconds in video
speed=1.2x             # Encoding 1.2x faster than realtime
```

**To calculate percent complete:**
```python
total_frames = metadata["duration"] * metadata["fps"]
current_frame = 150
percent = (current_frame / total_frames) * 100
```

---

## 🏗️ Scaling Strategy

### Small Scale (1-10 videos/hour)
```
1 Combined Worker (run_worker.py)
```

### Medium Scale (10-100 videos/hour)
```
2 Metadata Workers
4 Transcode Workers
```

### Large Scale (100+ videos/hour)
```
5 Metadata Workers
20 Transcode Workers (on GPU instances)
```

### Why Separate?
- **Metadata:** Fast, lightweight, high parallelism
- **Transcoding:** Slow, CPU-heavy, limited parallelism
- Different scaling needs = different worker pools

---

## 🐛 Common Issues

### 1. "width not divisible by 2"
**Cause:** Odd width from auto-scaling  
**Fix:** Use `scale=-2:720` instead of `scale=-1:720`

### 2. ffmpeg timeout
**Cause:** Video too large, timeout too short  
**Fix:** Increase timeout in workflow:
```python
start_to_close_timeout=timedelta(minutes=30)  # For 1+ hour videos
```

### 3. Out of memory
**Cause:** Too many concurrent transcode workers  
**Fix:** Limit workers based on available RAM:
```
RAM per worker: ~500 MB
8 GB RAM → Max 10-12 workers
```

### 4. Slow transcoding
**Cause:** CPU-bound, single-threaded ffmpeg  
**Solutions:**
- Use faster preset: `-preset fast` (lower quality)
- Use GPU encoding: `-c:v h264_nvenc` (requires NVIDIA GPU)
- Distribute across more workers

---

## 📚 Learn More

- [VIDEO_SCALING_EXPLAINED.md](../docs/VIDEO_SCALING_EXPLAINED.md) - Deep dive into scaling algorithms
- ffmpeg documentation: https://ffmpeg.org/documentation.html
- H.264 encoding guide: https://trac.ffmpeg.org/wiki/Encode/H.264

---

## 🎯 What's Implemented

✅ **Multiple resolutions:** 720p, 480p, 320p (auto-selected based on source)  
✅ **Parallel chunked transcoding:** N chunks × M resolutions  
✅ **HLS Adaptive Bitrate (ABR):**  
   - MPEG-TS segments (.ts) for each chunk  
   - Variant playlists per resolution  
   - Master playlist with bandwidth hints  
   - Players automatically switch quality based on network  

## 🚀 Next Steps (Enhancements)

1. **Add thumbnail extraction:**
   ```bash
   ffmpeg -i input.mp4 -ss 00:00:05 -vframes 1 thumbnail.jpg
   ```

2. **Add CDN integration:**
   - Connect MinIO/S3 bucket to CloudFront or Cloudflare
   - Set proper CORS headers for cross-origin playback

3. **Add audio normalization:**
   - Separate audio processing step for loudness normalization
   - EBU R128 or ATSC A/85 standards

4. **Add DASH support:**
   - Generate MPD manifests alongside HLS
   - fMP4 segments for better compression
