# Smart DAG Architecture - Video Transcoding Pipeline

> **Interview-Ready Documentation**: This document explains the conditional workflow orchestration pattern used in our video transcoding system. Perfect for system design discussions.

## Table of Contents
- [Executive Summary](#executive-summary)
- [The Problem: Why DAGs?](#the-problem-why-dags)
- [Architecture Evolution](#architecture-evolution)
- [Smart DAG Pattern](#smart-dag-pattern)
- [Conditional Branching](#conditional-branching)
- [Queue Architecture](#queue-architecture)
- [Failure Handling](#failure-handling)
- [Interview Deep-Dive Questions](#interview-deep-dive-questions)

---

## Executive Summary

Our video transcoding system uses a **Directed Acyclic Graph (DAG)** workflow pattern with **conditional branching** based on user-specified processing options. This allows us to:

1. **Skip unnecessary work** - Don't generate thumbnails if not requested
2. **Parallelize when possible** - Scene detection + transcoding can run concurrently
3. **Gracefully degrade** - Thumbnail failures don't block the main video
4. **Scale independently** - Different queues for different workloads

---

## The Problem: Why DAGs?

### Traditional Linear Pipeline
```
Upload → Extract Metadata → Transcode 480p → Transcode 720p → Transcode 1080p → Done
```

**Problems:**
- All videos follow same path regardless of needs
- 4K source? Still processes 480p first
- No thumbnails? Still allocates thumbnail workers
- One failure = entire pipeline fails

### DAG-Based Pipeline
```
                    ┌─→ Transcode 480p ─┐
                    │                    │
Upload → Metadata ──┼─→ Transcode 720p ─┼─→ Merge → Done
                    │                    │
                    └─→ Thumbnail ───────┘
                          (if requested)
```

**Benefits:**
- Conditional paths based on options
- Parallel execution where possible
- Independent failure domains

---

## Architecture Evolution

### Phase 1: Simple Sequential
```
┌──────────────────────────────────────────────────────────────┐
│  User Request                                                 │
│       ↓                                                       │
│  Download → Metadata → Transcode All → Generate Playlist      │
│                                                               │
│  Problems: Slow, no parallelism, one-size-fits-all            │
└──────────────────────────────────────────────────────────────┘
```

### Phase 2: Fan-Out Transcoding
```
┌──────────────────────────────────────────────────────────────┐
│  User Request                                                 │
│       ↓                                                       │
│  Download → Metadata → Split into Chunks                      │
│                              ↓                                │
│                    ┌─────────┼─────────┐                     │
│                    ↓         ↓         ↓                     │
│               Chunk 1    Chunk 2   Chunk 3  (parallel)       │
│                    ↓         ↓         ↓                     │
│                    └─────────┼─────────┘                     │
│                              ↓                                │
│                      Generate Playlist                        │
│                                                               │
│  Progress: Parallel chunk processing, still fixed path        │
└──────────────────────────────────────────────────────────────┘
```

### Phase 3: Smart DAG (Current)
```
┌──────────────────────────────────────────────────────────────────────┐
│  User Request + ProcessingOptions                                     │
│       ↓                                                               │
│  Download → Metadata ─┬─→ Thumbnail (if options.thumbnail)            │
│                       │                                               │
│                       ├─→ Scene Detection (if options.chapters)       │
│                       │        ↓                                      │
│                       │   Chapter Files (.vtt, .json, .m3u8)          │
│                       │                                               │
│                       └─→ Split Chunks                                │
│                                ↓                                      │
│                    ┌───────────┼───────────┐                         │
│                    ↓           ↓           ↓                         │
│               [480p]       [720p]      [1080p]   ← Dynamic based on  │
│               Chunks       Chunks      Chunks      source resolution │
│                    ↓           ↓           ↓                         │
│                    │     + watermark (if options.watermark)          │
│                    └───────────┼───────────┘                         │
│                                ↓                                      │
│                        Merge & Playlist                               │
│                                ↓                                      │
│                     Completion Workflow                               │
│                    (DB, cache, CDN, notify)                           │
│                                                                       │
│  Achievement: Conditional paths, parallel branches, graceful degrade  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Smart DAG Pattern

### ProcessingOptions Contract

```python
@dataclass
class ProcessingOptions:
    """User-specified processing configuration"""
    
    # Resolution selection - None means "auto-detect from source"
    resolutions: list[str] | None = None  # ["480p", "720p", "1080p"]
    
    # Thumbnail generation
    thumbnail: ThumbnailOptions | None = None
    
    # Watermark overlay
    watermark: WatermarkOptions | None = None
    
    # Chapter generation
    chapters: ChapterOptions | None = None
```

### Conditional Execution Pattern

```python
async def run(self, input: VideoInput):
    # Stage 1-3: Always execute (download, metadata, chunks)
    ...
    
    # Stage 4: Conditional Thumbnail Generation
    if input.options and input.options.thumbnail:
        try:
            await workflow.execute_activity(
                generate_thumbnail,
                args=[...],
                task_queue="metadata-queue",  # Reuse metadata workers
            )
        except Exception as e:
            # Log but don't fail - thumbnails are enhancement
            workflow.logger.warning(f"Thumbnail failed: {e}")
    
    # Stage 5: Conditional Scene Detection
    if input.options and input.options.chapters:
        # Similar pattern - non-critical path
        ...
    
    # Stage 6: Always execute - core transcoding
    # But with conditional watermark application
    ...
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Options are optional | Backward compatibility with existing clients |
| `None` = auto-detect | Smart defaults (e.g., resolutions from source) |
| Try/except on enhancements | Core transcoding shouldn't fail due to thumbnails |
| Separate queues | Different scaling profiles for different work |

---

## Conditional Branching

### Branch Types

#### 1. **Feature Branches** (User-Controlled)
```
if options.thumbnail:
    → Execute thumbnail generation
    
if options.watermark:
    → Add watermark filter to FFmpeg command
    
if options.chapters:
    → Run scene detection + chapter generation
```

#### 2. **Derived Branches** (System-Controlled)
```
source_height = metadata.height

if source_height >= 1080:
    → Generate 1080p, 720p, 480p
elif source_height >= 720:
    → Generate 720p, 480p
else:
    → Generate 480p only

# Don't upscale - waste of compute
```

#### 3. **Parallel Branches** (Performance)
```
# These can run simultaneously:
asyncio.gather(
    thumbnail_task,      # ~5 seconds
    scene_detection,     # ~30 seconds  
    split_chunks,        # ~10 seconds
)
```

### Branch Execution Visualization

```
                              ProcessingOptions
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
      thumbnail?               chapters?              resolutions?
            │                        │                        │
      ┌─────┴─────┐            ┌─────┴─────┐           ┌──────┴──────┐
      │           │            │           │           │             │
    True       False         True       False       Custom       Auto
      │           │            │           │           │             │
 Generate     Skip       Scene Det     Skip       Use List    From Source
 Thumbnail                + Files                              Resolution
```

---

## Queue Architecture

### Queue Topology

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            TEMPORAL SERVER                               │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │ video-tasks │    │download-    │    │ metadata-   │                 │
│  │   (workflows)│    │   queue     │    │   queue     │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
│         │                  │                  │                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │ split-queue │    │transcode-   │    │ playlist-   │                 │
│  │             │    │   queue     │    │   queue     │                 │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                 │
└─────────┼──────────────────┼──────────────────┼─────────────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
    ┌───────────┐     ┌───────────┐      ┌───────────┐
    │ Split     │     │ Transcode │      │ Playlist  │
    │ Worker    │     │ Workers   │      │ Worker    │
    │ (1 pod)   │     │ (N pods)  │      │ (1 pod)   │
    └───────────┘     └───────────┘      └───────────┘
```

### Queue Scaling Profiles

| Queue | Worker Count | Scaling Strategy | Reason |
|-------|-------------|------------------|--------|
| `video-tasks` | 1-2 | Fixed | Lightweight orchestration |
| `download-queue` | 2-5 | I/O bound | Network limited |
| `metadata-queue` | 2-5 | CPU light | Quick FFprobe calls |
| `split-queue` | 2-3 | Moderate | Fast FFmpeg split |
| `transcode-queue` | 5-50 | CPU heavy, auto-scale | Main compute |
| `playlist-queue` | 1-2 | Fixed | Fast file merge |

### Why Separate Queues?

```
Without Separate Queues:
┌──────────────────────────────────────┐
│  Single Queue                         │
│  ┌─────────────────────────────────┐ │
│  │ Download │ Metadata │ Transcode │ │
│  │   10s    │    2s    │   300s    │ │
│  └─────────────────────────────────┘ │
│                                       │
│  Problem: Transcode jobs starve       │
│  download jobs. Head-of-line blocking │
└──────────────────────────────────────┘

With Separate Queues:
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ Download Q    │ │ Metadata Q    │ │ Transcode Q   │
│ ┌───────────┐ │ │ ┌───────────┐ │ │ ┌───────────┐ │
│ │ 2 workers │ │ │ │ 2 workers │ │ │ │50 workers │ │
│ └───────────┘ │ │ └───────────┘ │ │ └───────────┘ │
└───────────────┘ └───────────────┘ └───────────────┘
                                          ↑
                            Heavy compute isolated
```

---

## Failure Handling

### Failure Domain Isolation

```
┌────────────────────────────────────────────────────────────────┐
│                      CRITICAL PATH                              │
│   Download → Metadata → Split → Transcode → Playlist            │
│                                                                 │
│   Failure here = Workflow fails, retry entire video             │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    ENHANCEMENT PATH                             │
│   Thumbnail Generation    Scene Detection    Chapter Files      │
│                                                                 │
│   Failure here = Log warning, continue without enhancement      │
│   Video still playable, just missing extra features             │
└────────────────────────────────────────────────────────────────┘
```

### Retry Strategy by Activity

```python
# Critical activities - aggressive retry
CRITICAL_RETRY = RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
)

# Enhancement activities - limited retry
ENHANCEMENT_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=2),
)

# Idempotent activities - safe to retry
# download_video: Re-downloads overwrite same file
# transcode_chunk: Deterministic output
# generate_playlist: Regenerates from chunks
```

### Graceful Degradation Example

```python
# In VideoWorkflow.run():

# Critical - must succeed
chunks_result = await workflow.execute_activity(
    split_video_into_chunks,
    retry_policy=CRITICAL_RETRY,
)

# Enhancement - can fail
thumbnail_url = None
if options.thumbnail:
    try:
        thumbnail_url = await workflow.execute_activity(
            generate_thumbnail,
            retry_policy=ENHANCEMENT_RETRY,
        )
    except ActivityError:
        workflow.logger.warning("Thumbnail generation failed, continuing...")
        # thumbnail_url stays None, video still works

# Continue with transcoding regardless of thumbnail result
```

---

## Interview Deep-Dive Questions

### Q1: "Why Temporal over Kafka/SQS?"

**Answer:**
```
Temporal provides:
1. Workflow state persistence - survives crashes
2. Built-in retry with backoff
3. Activity timeouts and heartbeats
4. Visual workflow debugging
5. Workflow versioning for deploys

Kafka would require:
- Manual state management
- Custom retry logic
- Saga pattern for multi-step
- Own observability tooling
```

### Q2: "How do you handle a 10GB video upload?"

**Answer:**
```
1. Chunked upload to S3/MinIO (presigned URLs)
2. Download activity streams to disk
3. Split activity creates N chunks
4. Each chunk transcoded independently
5. Playlist activity merges (just metadata)

Key: Never hold full video in memory
```

### Q3: "What if transcoding fails halfway?"

**Answer:**
```
1. Temporal persists workflow state
2. Retry policy attempts individual chunk
3. If chunk succeeds → continue
4. If max retries exceeded → workflow fails
5. Manual retry resumes from last checkpoint

Idempotency: Re-running same chunk produces same output
```

### Q4: "How would you add 4K support?"

**Answer:**
```
1. Update ProcessingOptions to allow "2160p"
2. Add resolution preset in chunked_transcode.py
3. Scale transcode-queue workers (more CPU)
4. Consider GPU workers for 4K specifically
5. Split into smaller chunks (longer encode time)

No workflow changes needed - just configuration
```

### Q5: "How do you prevent duplicate processing?"

**Answer:**
```
1. Temporal workflow ID = video_id (unique)
2. Starting duplicate workflow returns existing
3. Activities are idempotent by design
4. MinIO paths include video_id + resolution

workflow_id = f"transcode-{video_id}"
# Second request joins existing workflow
```

---

## Diagrams

See the `/docs/diagrams/` folder for D2 diagram source files:

- `01-high-level.d2` - Interview opener, 30-second overview
- `02-design-deep-dive.d2` - Queue architecture, 2-minute explanation  
- `03-final-architecture.d2` - Complete system, detailed discussion

Generate SVGs with:
```bash
d2 docs/diagrams/01-high-level.d2 docs/diagrams/01-high-level.svg
d2 docs/diagrams/02-design-deep-dive.d2 docs/diagrams/02-design-deep-dive.svg
d2 docs/diagrams/03-final-architecture.d2 docs/diagrams/03-final-architecture.svg
```

---

## Summary

The Smart DAG architecture provides:

| Feature | Benefit |
|---------|---------|
| Conditional Branching | Process only what's needed |
| Parallel Execution | Faster end-to-end time |
| Separate Queues | Independent scaling |
| Graceful Degradation | Robust to enhancement failures |
| Idempotent Activities | Safe retries |
| ProcessingOptions | Flexible API contract |

This pattern scales from hobby project to production-grade video platform.
