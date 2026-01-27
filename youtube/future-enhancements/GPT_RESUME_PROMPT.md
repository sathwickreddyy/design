# 🤖 GPT Resume Prompt

> **Purpose**: Copy/paste this into ChatGPT/Claude when resuming work on this project.

---

## 📋 Prompt for AI Assistant

```
I'm resuming work on a video transcoding system project. Here's the context:

PROJECT STATUS:
- Built a production-grade VOD (video on demand) transcoding system
- Uses Temporal workflows for orchestration, FFmpeg for processing, MinIO for storage
- Implements "Smart DAG" pattern with conditional branching
- Features: HLS streaming, thumbnail generation, watermark overlay, scene detection/chapters
- All current features are complete and working ✅

WHAT I'M DOING NEXT:
- Adding LIVE STREAMING capability (like Twitch/YouTube Live)
- This is separate from the VOD system (different architecture)
- Real-time processing constraints vs batch processing

TECHNICAL STACK:
- API: FastAPI (Python)
- Orchestration: Temporal
- Processing: FFmpeg
- Storage: MinIO (S3-compatible)
- Deployment: Docker Compose

PROJECT STRUCTURE:
youtube/
├── main.py                      # FastAPI app
├── shared/
│   ├── workflows.py             # VideoWorkflow (Smart DAG)
│   ├── storage.py               # MinIO helpers
│   └── router.py                # API routes
├── worker/
│   ├── activities/              # Processing activities
│   └── run_*_worker.py          # Worker registrations
├── docs/
│   ├── SMART_DAG_ARCHITECTURE.md
│   └── diagrams/                # D2 architecture diagrams
└── future-enhancements/
    ├── PROJECT_CONTEXT.md       # Detailed project summary
    └── live-streaming/          # Live streaming materials
        ├── LIVE_STREAMING_DESIGN_THINKING.md
        ├── LIVE_STREAMING_GUIDE.md
        └── *.svg                # Architecture diagrams

DOCUMENTATION AVAILABLE:
1. PROJECT_CONTEXT.md - Complete project summary, current state, future plans
2. LIVE_STREAMING_DESIGN_THINKING.md - Mental model for live streaming design
3. LIVE_STREAMING_GUIDE.md - Implementation guide and quick reference
4. Multiple architecture diagrams (D2 + SVG format)

WHAT I NEED HELP WITH:
[Describe what you want to work on, e.g.:]
- "Help me implement Phase 1: nginx-rtmp ingest server"
- "Review my current VOD architecture and suggest improvements"
- "Explain how to do real-time transcoding with FFmpeg"
- "Help me design the origin server for dynamic HLS playlists"
- "Debug an issue with [specific component]"

YOUR ROLE:
- Help me understand system design tradeoffs
- Guide implementation of new features
- Review code/architecture decisions
- Explain complex concepts (like HLS, RTMP, real-time processing)
- Help debug issues

IMPORTANT CONTEXT:
1. Current system is VOD (batch processing) - COMPLETE
2. New system is live streaming (stream processing) - TO BE BUILT
3. These are different architectures that will coexist
4. Don't modify existing VOD code when adding live features
5. Read PROJECT_CONTEXT.md if you need full background

COMMUNICATION PREFERENCES:
- Be concise but thorough
- Explain "why" not just "how"
- Point out tradeoffs and alternatives
- Use diagrams/examples when helpful
- Call out potential issues early

Ready to help?
```

---

## 🎯 Quick Context Snippets

Use these for specific scenarios:

### **Debugging Current VOD System**
```
I'm debugging an issue with my VOD transcoding system:
- Stack: Temporal + FastAPI + FFmpeg + MinIO
- Issue: [describe problem]
- Component affected: [workflow/activity/API]
- Error message: [paste error]
- What I've tried: [describe attempts]

The system uses Smart DAG workflows with conditional branching.
See PROJECT_CONTEXT.md for architecture details.
```

### **Starting Live Streaming Implementation**
```
I'm starting to implement live streaming for my video platform.

Current system: VOD transcoding (complete)
- Batch processing, parallel chunks, HLS output

New system: Live streaming (to be built)
- Real-time processing, RTMP ingest, dynamic playlists

I've already researched the architecture:
- See: future-enhancements/live-streaming/LIVE_STREAMING_DESIGN_THINKING.md
- Diagrams: live-01 through live-05.svg

Current phase: [Phase 1/2/3/4]
Help me with: [specific task]
```

### **Architecture Review Request**
```
I want you to review my video transcoding architecture:

System type: [VOD / Live Streaming / Both]
Focus area: [Workflows / Storage / API / Scaling / etc.]

Current approach: [describe]
Concerns: [what you're unsure about]

Files to review:
- [list relevant files]

Questions:
1. [specific question]
2. [specific question]
```

### **System Design Interview Prep**
```
I built a video transcoding system and want to practice explaining it for interviews.

System features:
- VOD transcoding with HLS streaming
- Smart DAG conditional workflows
- Thumbnail/watermark/chapters
- Queue-based architecture for scaling
- (Optional: Live streaming capability)

Interview scenario: [describe]
Help me:
- Structure my explanation
- Highlight key design decisions
- Prepare for deep-dive questions
- Practice trade-off discussions
```

---

## 📚 Reference Commands

Copy these for common tasks:

### **Start the System**
```bash
cd /Users/sathwick/my-office/system-design-learning/youtube/transcoding-engine-stack
docker-compose up -d
```

### **Test Video Upload**
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "options": {
      "resolutions": ["1080p", "720p"],
      "thumbnail": {"mode": "auto"},
      "watermark": {"text": "© Test", "position": "bottom_right"},
      "chapters": {"scene_threshold": 0.4}
    }
  }'
```

### **View Workflow in Temporal UI**
```
http://localhost:8080
```

### **Generate Diagrams from D2**
```bash
# Install D2 (if not installed)
brew install d2

# Generate single diagram
d2 docs/diagrams/03-final-architecture.d2 docs/diagrams/03-final-architecture.svg

# Generate all diagrams
for f in docs/diagrams/*.d2; do
  d2 "$f" "${f%.d2}.svg"
done
```

---

## 🔍 Key Concepts to Understand

When working with GPT, these concepts are important:

### **VOD vs Live Streaming**
```
VOD (Current):
- Complete file available
- Batch processing
- Parallel chunks
- Optimize for quality
- Storage: permanent

Live (Future):
- Continuous stream
- Real-time processing
- Serial segments
- Optimize for speed
- Storage: temporary (30s window)
```

### **Smart DAG Pattern**
```python
# Conditional workflow execution
if processing_options.thumbnail:
    thumbnail = await workflow.execute_activity(generate_thumbnail, ...)

if processing_options.watermark:
    # Apply during transcode
    ...

if processing_options.chapters:
    chapters = await workflow.execute_activity(detect_scenes, ...)
```

### **Queue Architecture**
```
download-queue:    I/O bound, 2-5 workers
metadata-queue:    Fast, 1-2 workers
transcode-queue:   CPU bound, 5-50 workers (scales)
playlist-queue:    Fast, 1-2 workers
```

### **HLS Streaming**
```
master.m3u8:
  ├─ 1080p/playlist.m3u8 → [segment1.ts, segment2.ts, ...]
  ├─ 720p/playlist.m3u8  → [segment1.ts, segment2.ts, ...]
  └─ 480p/playlist.m3u8  → [segment1.ts, segment2.ts, ...]
```

---

## 💾 Files to Share with GPT

When GPT needs more context, share these files:

1. **For architecture questions**: `docs/diagrams/*.svg` images
2. **For workflow logic**: `shared/workflows.py`
3. **For activity implementation**: `worker/activities/*.py`
4. **For live streaming design**: `future-enhancements/live-streaming/LIVE_STREAMING_DESIGN_THINKING.md`
5. **For complete context**: `future-enhancements/PROJECT_CONTEXT.md`

---

## ⚡ Example Conversations

### **Example 1: Implementing nginx-rtmp**
```
USER: "I'm ready to implement Phase 1 (nginx-rtmp ingest server). 
       I've read the live streaming design docs. 
       Help me set up nginx-rtmp in Docker."

GPT: [Provides nginx-rtmp Dockerfile, config, docker-compose integration]

USER: "How do I test this with OBS?"

GPT: [Provides OBS settings, stream key format, testing steps]
```

### **Example 2: Debugging VOD Issue**
```
USER: "My thumbnail generation is failing with error: 
       'No such filter: thumbnail'
       
       Using FFmpeg command:
       ffmpeg -i input.mp4 -vf thumbnail -frames:v 1 thumb.jpg"

GPT: [Explains thumbnail filter availability, suggests scale+select alternative]

USER: "Can you show me the correct FFmpeg command?"

GPT: [Provides working command with scale+select filters]
```

### **Example 3: Architecture Review**
```
USER: "I'm designing the origin server for live streaming.
       Should I use:
       A) FastAPI generating playlists on-demand
       B) Background job updating playlist files every 4s
       C) Redis pub/sub with in-memory playlist state
       
       My constraints: 1000 concurrent streams, 10k viewers"

GPT: [Analyzes tradeoffs, recommends hybrid approach with reasoning]
```

---

## 🎯 Success Criteria

You'll know GPT has enough context when:

✅ It understands your current VOD system
✅ It knows what's planned for live streaming
✅ It suggests solutions that fit your architecture
✅ It asks clarifying questions about your specific needs
✅ It references your existing code/docs appropriately

If GPT seems confused:
1. Share PROJECT_CONTEXT.md
2. Specify which component you're working on
3. Describe current vs desired state
4. Share relevant diagram/code snippet

---

## 🚀 Ready to Resume!

Copy the main prompt above when you're ready to start working again. Customize the "WHAT I NEED HELP WITH" section for your specific task.

Good luck! 🎬
