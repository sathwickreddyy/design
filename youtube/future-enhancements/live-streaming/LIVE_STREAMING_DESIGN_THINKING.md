# Live Streaming Architecture - Mental Model & Design Thinking

> **Learning Goal**: Understand how to think about real-time video systems vs batch processing systems

## 🎯 The Fundamental Paradigm Shift

### VOD (Your Current System)
```
Complete Video → Upload → Process → Store → Serve
                 ↓
            "I have all the data"
            Can retry, reprocess, optimize
```

### Live Streaming
```
Continuous Stream → Process in real-time → Serve immediately
                    ↓
            "I only have the current moment"
            Can't go back, must keep up
```

---

## 🤔 Design Thinking Framework for Real-Time Systems

### Step 1: Question Your Assumptions

| VOD Assumption | Live Streaming Reality | Design Impact |
|----------------|------------------------|---------------|
| "Video file exists" | No file - continuous stream | Need stream buffer |
| "Can retry failed chunks" | Lost frames = lost forever | Need redundancy |
| "Process then serve" | Must serve while processing | Need low latency pipeline |
| "Store everything" | Can't store infinite stream | Need rolling window |
| "One user uploads" | Multiple concurrent streams | Need multiplexing |

### Step 2: Identify Constraints

**Real-Time Constraints:**
1. **Latency Budget**: Must process chunk in < chunk duration (e.g., 4s chunk in 3s)
2. **Continuous Data**: No "end" - streams can be hours/days
3. **Failure Modes**: Dropped frames, network hiccups, encoder crashes
4. **Resource Limits**: Can't buffer entire stream in memory

### Step 3: What Changes?

```
VOD:        Upload (minutes) → Process (hours) → Watch (anytime)
            Optimized for: Thoroughness

Live:       Stream (continuous) → Process (< 2s) → Watch (now)
            Optimized for: Speed
```

---

## 🏗 Architectural Changes Needed

### Current VOD Architecture (What You Have)
```
┌──────────────────────────────────────────────────────────────┐
│  User Upload                                                  │
│      ↓                                                        │
│  Complete File in Storage                                     │
│      ↓                                                        │
│  Temporal Workflow (Batch Processing)                         │
│      ↓                                                        │
│  Chunks → Parallel Workers → Merge                            │
│      ↓                                                        │
│  HLS Playlist (Static)                                        │
└──────────────────────────────────────────────────────────────┘
```

### Live Streaming Architecture (What You Need)
```
┌──────────────────────────────────────────────────────────────┐
│  Camera/Encoder (OBS, FFmpeg)                                 │
│      ↓                                                        │
│  INGEST SERVER (New Component!)                               │
│  - Accept RTMP/WebRTC stream                                  │
│  - Buffer incoming frames                                     │
│      ↓                                                        │
│  LIVE TRANSCODER (Different from VOD!)                        │
│  - Process chunks as they arrive                              │
│  - Must keep up with real-time                                │
│      ↓                                                        │
│  ORIGIN SERVER (New Component!)                               │
│  - Generate HLS segments on-the-fly                           │
│  - Update playlist continuously                               │
│      ↓                                                        │
│  CDN / Edge Cache                                             │
│  - Serve viewers with low latency                             │
└──────────────────────────────────────────────────────────────┘
```

---

## 🧩 New Components & Why We Need Them

### 1. **Ingest Server** (New!)

**Purpose**: Accept continuous video stream from encoder

**Why Needed?**
- VOD: User uploads complete file via HTTP POST
- Live: Continuous push from encoder via RTMP/WebRTC

**Technology Options:**
- **RTMP**: nginx-rtmp-module (stable, proven)
- **WebRTC**: Janus, Mediasoup (lower latency)
- **SRT**: Better for long distance, poor networks

**What It Does:**
```
Encoder → [TCP Connection] → Ingest Server
                                   ↓
                            Buffers video frames
                            Groups into segments (4-6s)
                            Passes to transcoder
```

### 2. **Live Transcoder** (Modified!)

**Differences from VOD Transcoder:**

| Aspect | VOD Transcoder | Live Transcoder |
|--------|----------------|-----------------|
| Input | File chunks | Stream buffer |
| Latency | Can be slow | Must be < segment duration |
| Retries | Safe to retry | Can't retry - data gone |
| Scaling | Based on queue | Based on streams |
| State | Stateless | Stateful (per stream) |

**Why Different?**
- Can't wait for "all chunks" - process as data arrives
- Must maintain constant throughput
- Needs real-time presets (faster, lower quality)

### 3. **Origin Server** (New!)

**Purpose**: Generate and serve HLS playlists in real-time

**Why Needed?**
- VOD: Static playlist, generated once
- Live: Dynamic playlist, updated every segment

**What It Does:**
```
# VOD Playlist (static)
#EXTM3U
#EXT-X-ENDLIST  ← Signals "complete"
seg_000.ts
seg_001.ts
seg_002.ts

# Live Playlist (dynamic)
#EXTM3U
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:1234  ← Keeps incrementing
seg_1234.ts
seg_1235.ts
seg_1236.ts
(No #EXT-X-ENDLIST - still going!)
```

### 4. **State Manager** (New!)

**Purpose**: Track active streams, viewers, quality

**Why Needed?**
- Need to know which streams are live
- Track how many viewers per stream
- Manage stream lifecycle (start/stop)
- Handle reconnections

---

## 🎬 Live Streaming Flow (Step-by-Step)

### Phase 1: Stream Start (Broadcaster)

```
1. Broadcaster opens OBS/mobile app
2. Clicks "Go Live"
3. App sends RTMP handshake to Ingest Server
4. Ingest allocates stream ID: "stream_abc123"
5. State Manager marks stream as "LIVE"
```

### Phase 2: Continuous Processing

```
Every 4 seconds (segment duration):

Encoder → Sends 4s of video → Ingest Server
                                    ↓
                            Writes to buffer
                                    ↓
                            Live Transcoder reads buffer
                                    ↓
                            Transcodes to 720p, 480p, 360p
                            (Must finish in < 4s!)
                                    ↓
                            Origin Server receives segments
                                    ↓
                            Updates HLS playlist
                                    ↓
                            CDN pulls new segment
                                    ↓
                            Viewers' players fetch segment
```

### Phase 3: Viewing (Audience)

```
Viewer opens player:
1. Player fetches master.m3u8
2. Sees stream is LIVE (no #EXT-X-ENDLIST)
3. Fetches latest segments
4. Plays segment
5. Waits 4s
6. Fetches next segment (playlist updates)
7. Repeat steps 4-6 until stream ends
```

---

## 🔄 Key Differences in Data Flow

### VOD Data Flow (Pull-based)
```
Storage → Workflow pulls data → Processes → Writes back

Characteristics:
- Data at rest
- Process at leisure
- Can parallelize easily
```

### Live Data Flow (Push-based)
```
Source pushes data → Process immediately → Forward downstream

Characteristics:
- Data in motion
- Process under time pressure
- Serial processing per stream
```

---

## 💾 Storage Pattern Changes

### VOD Storage (Your Current System)
```
videos/
  video_123/
    source/source.mp4          (Permanent)
    outputs/
      720p/segments/           (Permanent)
        seg_000.ts ... seg_N.ts
      master.m3u8              (Permanent)
```

### Live Storage (Sliding Window)
```
live-streams/
  stream_abc/
    segments/
      seg_1000.ts  (Delete after 30s)
      seg_1001.ts  (Delete after 30s)
      seg_1002.ts  (Keep latest 5-10)
      seg_1003.ts  (Current)
    playlist.m3u8  (Regenerate every 4s)

Recording (Optional):
  archives/
    stream_abc_2024-01-27.mp4  (If user wants VOD)
```

**Why Sliding Window?**
- Can't store infinite stream
- Viewers only need recent segments
- Old segments are useless (already watched)

---

## 🎯 Design Principles for Real-Time Systems

### 1. **Time is a Resource**
```
VOD:  time = "how long it takes"
Live: time = "must happen by deadline"

Design Impact:
- Profile every operation
- Set timeouts everywhere
- Have fallback paths
```

### 2. **Statefulness vs Statelessness**
```
VOD Workers:  Stateless (any worker, any chunk)
Live Workers: Stateful (one worker per stream)

Design Impact:
- Need session management
- Handle worker crashes differently
- Can't easily scale horizontally
```

### 3. **Backpressure Handling**
```
VOD:  Queue grows → Add workers → Catch up
Live: Can't queue → Must drop frames or reduce quality

Design Impact:
- Need quality adaptation
- Need frame dropping logic
- Monitor buffer depth
```

---

## 🧠 Thought Process: How to Approach This Problem

### Mental Framework (STAR Method)

**S - Situation**: User wants to live stream
**T - Task**: Design real-time video processing
**A - Approach**: Break down into stages
**R - Result**: Production-grade live streaming

### Breaking Down the Problem

#### Question 1: "How does data enter the system?"
```
VOD:  HTTP POST (complete file)
Live: Streaming protocol (RTMP/WebRTC)
      → Need protocol server (nginx-rtmp)
```

#### Question 2: "What's the latency budget?"
```
Target: 5-15 second delay (acceptable for live)
        2-3 second delay (low-latency HLS)

Breakdown:
- Encoder: 2s (buffer + encode)
- Network: 1s (upload)
- Transcode: 2s (must be < segment duration)
- CDN: 1s (propagation)
- Player buffer: 6s (smoothing)
= ~12s total delay
```

#### Question 3: "What happens when something is slow?"
```
VOD:  Retry, requeue, wait
Live: Drop frames, lower quality, skip segment

Decision Tree:
If transcode_time > segment_duration:
    - Lower encoding preset (faster)
    - Skip a quality variant
    - Drop segment (player will buffer)
```

#### Question 4: "How do we scale?"
```
VOD:  Scale workers horizontally (any chunk, any worker)
Live: Scale per-stream (one stream = one worker group)

Calculation:
- 1 stream = 1 transcoder core per quality
- 1000 concurrent streams = 3000 cores (3 qualities)
- Need auto-scaling based on active streams
```

---

## 📊 Comparison Table

| Aspect | VOD (Current) | Live Streaming | Why Different? |
|--------|---------------|----------------|----------------|
| **Input** | Complete file | Continuous stream | Live has no "end" |
| **Processing** | Batch (parallel) | Real-time (serial) | Must keep up with time |
| **Storage** | Permanent | Temporary (sliding) | Infinite data problem |
| **Playlist** | Static | Dynamic | Keeps growing |
| **Latency** | Minutes to hours | Seconds | User expectation |
| **Failure** | Retry entire job | Drop frames | Can't go back |
| **Scaling** | Worker count | Stream count | Different bottleneck |
| **Cost** | Per video | Per minute streaming | Different pricing |

---

## 🎓 Interview Talking Points

### "How would you design a live streaming system?"

**Answer Structure:**

1. **Clarify Requirements**
   - "How many concurrent streams?"
   - "What latency is acceptable?"
   - "Do we need recording (VOD after)?"

2. **Identify Constraints**
   - "Must process in real-time (< segment duration)"
   - "Can't store infinite stream"
   - "Need to handle network issues"

3. **Component Breakdown**
   - Ingest (RTMP server)
   - Transcode (real-time encoder)
   - Origin (HLS packager)
   - CDN (distribution)

4. **Scale Considerations**
   - "1000 streams = 3000 transcoding cores"
   - "CDN for viewer distribution"
   - "Ingest servers per region"

5. **Failure Modes**
   - "Broadcaster disconnect → End stream gracefully"
   - "Transcoder slow → Drop quality variant"
   - "CDN issue → Multi-CDN failover"

---

## 🔄 Next Steps: Diagrams

I'll now create visual diagrams showing:
1. Live streaming architecture
2. Data flow comparison (VOD vs Live)
3. Component interaction timeline
4. Failure scenarios
5. Scaling patterns

Let me create these diagrams...
