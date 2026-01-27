# Smart DAG Flow Visualizations

This folder contains D2 diagrams showing how the workflow dynamically branches based on different `ProcessingOptions`.

## 📊 Flow Diagrams

| Diagram | Scenario | Key Features |
|---------|----------|--------------|
| [flow-01-basic.d2](flow-01-basic.d2) | No options | Only critical path (download → transcode → playlist) |
| [flow-02-thumbnail.d2](flow-02-thumbnail.d2) | Thumbnail only | Shows parallel thumbnail generation |
| [flow-03-watermark.d2](flow-03-watermark.d2) | Watermark only | Watermark embedded in transcode stage |
| [flow-04-chapters.d2](flow-04-chapters.d2) | Chapters only | Scene detection → chapter files (VTT/JSON/HLS) |
| [flow-05-all-features.d2](flow-05-all-features.d2) | All features | Full parallel execution of enhancements |
| [flow-06-custom-resolution.d2](flow-06-custom-resolution.d2) | Custom resolutions | Targeted transcode (skip unnecessary resolutions) |
| [flow-07-graceful-degradation.d2](flow-07-graceful-degradation.d2) | Failure handling | Shows try/catch pattern, video continues |

## 🎨 Color Legend

- **Blue** (#2196f3): Core activities (download, metadata, split)
- **Orange** (#ff9800): Transcode activities (critical path, CPU-heavy)
- **Red** (#ff5722): Enhanced transcode (with watermark)
- **Cyan** (#00bcd4): Thumbnail generation (enhancement)
- **Purple** (#673ab7): Scene detection & chapters (enhancement)
- **Green** (#4caf50): Start/End/Success
- **Gray** (dashed): Skipped stages

## 🎯 Understanding the Flows

### Critical Path vs Enhancement Path

```
Critical Path (MUST succeed):
  Download → Metadata → Split → Transcode → Playlist
  
Enhancement Path (CAN fail gracefully):
  Thumbnail, Scene Detection, Chapters
```

### Parallel Execution Pattern

When multiple enhancements are requested, they run **in parallel** with transcoding:

```
Split → ┬─→ Thumbnail ──────┐
        │                   │
        ├─→ Scene Detection ─┤ All run in parallel
        │                   │
        └─→ Transcode ───────┘
                ↓
            Merge results
```

### Dynamic Branching Logic

The workflow uses conditional logic:

```python
# In VideoWorkflow.run()

# Thumbnail branch
if input.options and input.options.thumbnail:
    try:
        thumbnail_url = await execute_activity(generate_thumbnail, ...)
    except ActivityError:
        logger.warning("Thumbnail failed, continuing...")

# Chapters branch  
if input.options and input.options.chapters:
    try:
        scenes = await execute_activity(detect_scenes, ...)
        await execute_activity(generate_chapter_files, scenes)
    except ActivityError:
        logger.warning("Chapter generation failed, continuing...")

# Watermark branch (embedded in transcode)
for chunk in chunks:
    watermark_params = input.options.watermark if input.options else None
    await execute_activity(
        transcode_chunk,
        args=[chunk, resolution, watermark_params],
        ...
    )
```

## 🚀 Generate SVG Images

```bash
# Generate all flow diagrams
cd /Users/sathwick/my-office/system-design-learning/youtube/docs/diagrams

for file in flow-*.d2; do
    d2 "$file" "${file%.d2}.svg"
done

# Or individually:
d2 flow-01-basic.d2 flow-01-basic.svg
d2 flow-02-thumbnail.d2 flow-02-thumbnail.svg
d2 flow-03-watermark.d2 flow-03-watermark.svg
d2 flow-04-chapters.d2 flow-04-chapters.svg
d2 flow-05-all-features.d2 flow-05-all-features.svg
d2 flow-06-custom-resolution.d2 flow-06-custom-resolution.svg
d2 flow-07-graceful-degradation.d2 flow-07-graceful-degradation.svg
```

## 🧪 Testing Each Scenario

### Scenario 1: Basic
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtube.com/watch?v=..."}'
```

### Scenario 2: Thumbnail
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {"thumbnail": {"mode": "auto"}}
  }'
```

### Scenario 3: Watermark
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "watermark": {
        "text": "© Brand",
        "position": "bottom_right"
      }
    }
  }'
```

### Scenario 4: Chapters
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "chapters": {"scene_threshold": 0.4}
    }
  }'
```

### Scenario 5: All Features
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "thumbnail": {"mode": "scene_based"},
      "watermark": {"text": "© 2024", "position": "center"},
      "chapters": {"scene_threshold": 0.3}
    }
  }'
```

### Scenario 6: Custom Resolution
```bash
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "resolutions": ["1080p"]
    }
  }'
```

### Scenario 7: Test Graceful Degradation
```bash
# Force thumbnail failure with invalid timestamp
curl -X POST "http://localhost:8000/videos" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://youtube.com/watch?v=...",
    "options": {
      "thumbnail": {
        "mode": "timestamp",
        "custom_time_seconds": 99999
      }
    }
  }'

# Video should still complete successfully
# Check Temporal UI for warning logs
```

## 🎓 Interview Talking Points

Use these diagrams to explain:

1. **Conditional Execution**: "Based on user options, the workflow dynamically creates different execution paths"
   
2. **Parallel Processing**: "Enhancement tasks run in parallel with transcoding to minimize latency"
   
3. **Fault Isolation**: "Thumbnail failures don't affect video processing - graceful degradation"
   
4. **Resource Optimization**: "Custom resolutions skip unnecessary work - faster and cheaper"
   
5. **Idempotency**: "Each activity is deterministic - safe to retry on failure"

## 📖 Related Documentation

- [SMART_DAG_ARCHITECTURE.md](../SMART_DAG_ARCHITECTURE.md) - Complete architecture explanation
- [workflows.py](../../shared/workflows.py) - Actual workflow implementation
- [README.md](../../README.md) - Project overview
