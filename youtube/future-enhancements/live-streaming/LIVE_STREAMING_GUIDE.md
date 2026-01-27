# 🎥 Live Streaming vs VOD: Complete Learning Guide

> **Goal**: Understand how to think about and design real-time video systems

## 📚 Study Path

### 1. Start Here: [LIVE_STREAMING_DESIGN_THINKING.md](../LIVE_STREAMING_DESIGN_THINKING.md)
   - Mental model shift (VOD → Live)
   - Design thinking framework
   - Component reasoning
   - Interview preparation

### 2. Visual Diagrams (This Folder)

| Diagram | What It Shows | When to Use |
|---------|---------------|-------------|
| [live-01-vod-vs-live.svg](live-01-vod-vs-live.svg) | Side-by-side comparison | Interview opener: "Here's the difference..." |
| [live-02-complete-architecture.svg](live-02-complete-architecture.svg) | Full system with all components | Deep dive: "Let me show you each piece..." |
| [live-03-timeline-flow.svg](live-03-timeline-flow.svg) | What happens every 4 seconds | Explain real-time constraints |
| [live-04-hybrid-system.svg](live-04-hybrid-system.svg) | How to add live to your VOD system | Implementation discussion |
| [live-05-failure-scenarios.svg](live-05-failure-scenarios.svg) | Failure modes & recovery | Resilience discussion |

---

## 🎯 Key Concepts to Master

### 1. **Push vs Pull Architecture**

```
VOD (Pull):
  Storage → Workers pull data → Process → Write back
  
Live (Push):
  Encoder pushes → Process immediately → Forward downstream
```

**Why Different?**
- Pull: Workers control pace (can parallelize)
- Push: Source controls pace (must keep up)

### 2. **Time as a Constraint**

```
VOD:  Time = "How long it takes"
      Can process for hours
      
Live: Time = "Must finish by deadline"
      Must process segment in < segment duration
```

**Mental Model:**
- VOD: Optimize for quality
- Live: Optimize for speed

### 3. **State Management**

```
VOD Workers:  Stateless
  - Any worker can process any chunk
  - Easy horizontal scaling
  
Live Workers: Stateful
  - One worker assigned per stream
  - Maintains buffer state
  - Harder to scale
```

### 4. **Storage Patterns**

```
VOD:     Permanent storage (GB → TB)
Live:    Sliding window (keep last 30s)
Archive: Optional recording → becomes VOD
```

---

## 🏗 Architecture Differences Summary

| Aspect | VOD | Live | Why? |
|--------|-----|------|------|
| **Input** | Complete file | Continuous stream | Live has no end |
| **Entry Point** | HTTP POST | RTMP/WebRTC | Different protocols |
| **Processing** | Batch (parallel chunks) | Real-time (serial segments) | Time constraints |
| **Workers** | Stateless pool | Stateful per-stream | Stream continuity |
| **Playlist** | Static, generated once | Dynamic, updates every 4s | Still streaming |
| **Storage** | Permanent | Temporary (30s window) | Can't store infinity |
| **Latency** | Minutes to hours OK | Must be < 15 seconds | User expectation |
| **Failure** | Retry entire chunk | Drop frames/lower quality | Can't go back in time |
| **Scaling** | Add more workers | Add capacity per stream | Different bottleneck |
| **Cost** | Per video processed | Per minute streaming | Continuous resources |

---

## 🧩 New Components Needed

### 1. **Ingest Server** (nginx-rtmp or Wowza)
```
Purpose:  Accept continuous RTMP/WebRTC streams
Why:      HTTP POST doesn't work for continuous data
Scale:    1-2 per region
Cost:     $50-100/month per instance
```

### 2. **Live Transcoder** (Different from VOD!)
```
Purpose:  Transcode segments in real-time
Why:      Must process in < 4s (segment duration)
Preset:   "ultrafast" + "zerolatency" (fast but lower quality)
Scale:    1 core per stream per quality = 3 cores/stream
```

### 3. **Origin Server**
```
Purpose:  Generate and serve dynamic HLS playlists
Why:      Playlist keeps growing (no #EXT-X-ENDLIST)
Update:   Every 4 seconds with new segment
Tech:     FastAPI + Redis (for segment metadata)
```

### 4. **Stream State Manager** (Redis)
```
Purpose:  Track active streams, viewers, health
Data:
  - stream_id → status (LIVE, ENDED)
  - stream_id → start_time
  - stream_id → viewer_count
  - stream_id → quality_variants
```

---

## 🎬 Data Flow: Step by Step

### Phase 1: Stream Start
```
1. Broadcaster opens OBS
2. Clicks "Go Live"
3. OBS → RTMP handshake → Ingest Server (port 1935)
4. Ingest allocates stream_id: "stream_abc123"
5. State Manager: SET stream_abc123 = LIVE
6. Ingest → Start buffering incoming frames
```

### Phase 2: Continuous Processing (Every 4s)
```
T=0s:  Encoder captures frames 0-120 (4s @ 30fps)
T=2s:  Ingest has buffered 2s of data
T=4s:  Ingest completes segment 0
       → Pass to Live Transcoder
       
T=4s-6s: Live Transcoder processes segment 0
         - Transcode to 1080p, 720p, 480p
         - Must finish in < 4s!
         - Write segments to storage
         
T=6s:  Origin Server receives segments
       - Update playlist.m3u8:
         #EXT-X-MEDIA-SEQUENCE:0
         seg_0000.ts
       - CDN pulls new segment
       
T=6s+: Viewers' players fetch segment 0
       - Playback starts
       - ~10s latency (acceptable)
```

### Phase 3: Ongoing (Every 4s, Forever)
```
T=4s:  Segment 1 capturing
T=8s:  Segment 1 ready, segment 2 capturing
T=12s: Segment 2 ready, segment 3 capturing
...

At T=8s, system has:
- Segment 0: Being watched by viewers
- Segment 1: Being transcoded
- Segment 2: Being ingested
- Segment 3: Being captured

= 4 segments in different stages simultaneously
```

---

## 🧠 Design Thinking Process

### When Given a Live Streaming Problem:

#### Step 1: **Clarify Requirements**
```
Questions to Ask:
- How many concurrent streams? (1? 100? 10,000?)
- What latency is acceptable? (2s? 15s? 30s?)
- Do users need recordings? (VOD after live?)
- Geographic distribution? (Single region? Global?)
- Expected viewer count per stream? (10? 1000? 100k?)
```

#### Step 2: **Identify Constraints**
```
Time Constraints:
- Must process segment in < segment duration
- Latency budget: 5-15 seconds acceptable

Resource Constraints:
- Can't buffer entire stream in memory
- Can't store all segments forever

Consistency Constraints:
- All viewers must see same content
- No viewer should be > 30s behind
```

#### Step 3: **Break Down Into Stages**
```
Stage 1: How does data enter? → Ingest Server
Stage 2: How to process real-time? → Live Transcoder
Stage 3: How to serve dynamically? → Origin Server
Stage 4: How to distribute? → CDN
Stage 5: How to handle failures? → Redundancy + Degradation
```

#### Step 4: **Think Through Failure Modes**
```
What if...
- Broadcaster disconnects? → 30s grace period, allow reconnect
- Transcoder too slow? → Drop quality variant or faster preset
- Origin crashes? → Failover to standby, reconstruct from Redis
- CDN saturated? → Multi-CDN failover, adaptive bitrate
```

#### Step 5: **Calculate Scale**
```
Example: 1000 concurrent streams

Ingest:
- 1 stream = 4 Mbps upload
- 1000 streams = 4 Gbps total
- Need 2-3 ingest servers (load balanced)

Transcoding:
- 1 stream = 3 quality variants
- 1 variant = 1 CPU core
- 1000 streams = 3000 CPU cores
- = 375 x c5.2xlarge instances (8 cores each)
- = $50,000/month (on-demand) or $15,000 (spot)

Storage:
- Keep 30s window per stream
- 1 stream = 15 MB (30s × 4 Mbps ÷ 8)
- 1000 streams = 15 GB active at once
- Cheap!

CDN:
- 1000 streams × 1000 viewers each = 1M viewers
- 1 viewer = 2.5 Mbps average
- = 2.5 Tbps total
- = $50,000-100,000/month CDN costs
```

---

## 🎓 Interview Framework

### "Design a Live Streaming System like Twitch"

**Answer Structure (15 minutes):**

**1. Clarify (2 min)**
```
- "How many concurrent streamers?"
- "What's the latency requirement?"
- "Do we need DVR (rewind/pause live)?"
- "Global or single region?"
```

**2. High-Level Architecture (3 min)**
```
Draw:
[Broadcaster] → [Ingest] → [Transcode] → [Origin] → [CDN] → [Viewers]

Explain each component briefly
```

**3. Deep Dive: Ingest (2 min)**
```
- Protocol: RTMP or WebRTC
- Load balancing: Round-robin to available servers
- Authentication: Stream key validation
- Monitoring: Detect disconnects
```

**4. Deep Dive: Transcoding (3 min)**
```
- Real-time constraint: Must finish in < 4s
- Presets: ultrafast + zerolatency
- Quality variants: 1080p, 720p, 480p
- Scaling: Auto-scale based on active streams
```

**5. Deep Dive: Distribution (2 min)**
```
- Origin: Dynamic HLS playlist generation
- CDN: Multi-CDN for resilience
- Adaptive bitrate: Players choose quality
```

**6. Failure Handling (2 min)**
```
- Broadcaster disconnect: 30s grace, allow reconnect
- Transcoder overload: Drop quality variant
- Origin crash: Failover to standby
- CDN issue: Multi-CDN + adaptive bitrate
```

**7. Scale Calculation (1 min)**
```
1000 streams:
- Ingest: 2-3 servers
- Transcode: 3000 CPU cores
- Storage: 15 GB active
- CDN: 2.5 Tbps (with viewers)
- Cost: ~$75,000/month
```

---

## 🔑 Key Takeaways

### 1. **Fundamental Paradigm Shift**
```
VOD = Batch Processing = Optimize for Quality
Live = Stream Processing = Optimize for Speed
```

### 2. **New Components are Necessary**
```
You CANNOT repurpose VOD architecture for live
Need: Ingest, Real-time Transcoder, Origin, State Manager
```

### 3. **Statefulness Changes Everything**
```
VOD: Stateless workers → Easy horizontal scaling
Live: Stateful workers → Complex session management
```

### 4. **Time is a Hard Constraint**
```
If processing > segment duration:
→ Buffer grows → Latency increases → System fails
Solution: Faster presets, more cores, drop quality
```

### 5. **Graceful Degradation is Key**
```
Better to drop to 480p than to crash
Better to drop a frame than to buffer forever
Better to lose quality than to lose availability
```

---

## 🚀 Next Steps

### To Build This System:

**Phase 1: Proof of Concept (1-2 weeks)**
```
- Deploy nginx-rtmp on EC2
- Test OBS → Ingest → FFmpeg transcode → HLS output
- Serve HLS via nginx
- Test with VLC player
```

**Phase 2: Production Grade (4-6 weeks)**
```
- Add Origin server (FastAPI + Redis)
- Implement live transcoder workers
- Add CDN integration (CloudFront)
- Build monitoring (Prometheus + Grafana)
```

**Phase 3: Scale (2-4 weeks)**
```
- Auto-scaling for transcoders
- Multi-region ingest
- Multi-CDN failover
- Advanced monitoring & alerting
```

---

## 📖 Additional Resources

- [nginx-rtmp-module](https://github.com/arut/nginx-rtmp-module)
- [FFmpeg Streaming Guide](https://trac.ffmpeg.org/wiki/StreamingGuide)
- [HLS Specification (RFC 8216)](https://datatracker.ietf.org/doc/html/rfc8216)
- [AWS MediaLive Documentation](https://docs.aws.amazon.com/medialive/)
- [Twitch Engineering Blog](https://blog.twitch.tv/en/tags/engineering/)

---

## 🎯 Practice Questions

1. "How would you reduce latency from 15s to 3s?" (HLS Low-Latency)
2. "What if 10,000 viewers join a stream in 10 seconds?" (Flash crowd handling)
3. "How do you handle a broadcaster with unstable internet?" (Adaptive upload bitrate)
4. "Can viewers rewind during a live stream?" (DVR functionality)
5. "How would you add live chat?" (WebSocket at scale)

Good luck with your learning! 🚀
