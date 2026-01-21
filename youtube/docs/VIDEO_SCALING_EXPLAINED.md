# 🎬 Video Scaling Deep Dive: What Happens When Converting 1080p → 720p?

## The Fundamental Problem

**Original video:** 1920×1080 pixels per frame = **2,073,600 pixels**  
**Target video:** 1280×720 pixels per frame = **921,600 pixels**

**Challenge:** How do we "throw away" 1,152,000 pixels per frame without making it look terrible?

---

## The Scaling Algorithm (Downsampling)

### 1. **Aspect Ratio Preservation**

```
Original: 1920 ÷ 1080 = 1.777... (16:9)
Target:   1280 ÷ 720  = 1.777... (16:9)
✅ Same aspect ratio = no distortion!
```

If we didn't preserve aspect ratio:
```
BAD: 1920x1080 → 1000x720
     1.777     →  1.388     ❌ Squished horizontally!
```

### 2. **Pixel Averaging (Bilinear Interpolation)**

ffmpeg uses **bilinear interpolation** by default. Here's how:

**Visual Example:**
```
Original 1920x1080 grid:
Every 1.5 pixels → 1 pixel in 720p

┌──┬──┬──┬──┬──┬──┐
│ A│ B│ C│ D│ E│ F│  Original row (1920 pixels)
└──┴──┴──┴──┴──┴──┘
   ↓  ↓  ↓  ↓  ↓
┌────┬────┬────┬────┐
│ AB │ CD │ EF │... │  Scaled row (1280 pixels)
└────┴────┴────┴────┘

Each new pixel = weighted average of ~2.25 surrounding pixels
```

**Numerical Example:**
```
Original 2×2 pixels:          Scaled to 1×1 pixel:
┌────┬────┐
│ 50 │ 60 │                      ┌────┐
├────┼────┤        →             │ 57 │
│ 55 │ 65 │                      └────┘
└────┴────┘
                        New pixel = (50+60+55+65)/4 = 57.5 ≈ 57
```

### 3. **The Full Transformation**

```
┌─────────────────────────────────────────────┐
│  STEP 1: Read compressed video (h264)       │
│  File: 150 MB                                │
└─────────────────────────────────────────────┘
              ↓ (Decode)
┌─────────────────────────────────────────────┐
│  STEP 2: Decompress to raw frames in RAM    │
│  1920x1080x3 bytes per frame (RGB)          │
│  = 6,220,800 bytes per frame                │
│  At 30fps: ~186 MB/second in memory!        │
└─────────────────────────────────────────────┘
              ↓ (Scale with -vf scale=-2:720)
┌─────────────────────────────────────────────┐
│  STEP 3: Resize each frame                  │
│  Algorithm: Bilinear interpolation           │
│  For each output pixel:                      │
│    - Find corresponding input position       │
│    - Average surrounding 2-4 input pixels    │
│  Result: 1280x720x3 = 2,764,800 bytes/frame │
└─────────────────────────────────────────────┘
              ↓ (Encode with libx264)
┌─────────────────────────────────────────────┐
│  STEP 4: Compress to h264 @ 720p            │
│  Quality: CRF 23 (visually transparent)      │
│  Output: 60 MB (60% file size reduction!)   │
└─────────────────────────────────────────────┘
```

---

## The `scale=-2:720` Magic Explained

**Your ffmpeg command:**
```bash
-vf "scale=-2:720"
```

**Breakdown:**
- `scale=width:height` - Resize filter
- `-2` - Special value meaning "auto-calculate width to maintain aspect ratio AND ensure divisible by 2"
- `720` - Target height

**Why `-2` instead of `-1`?**

```
-1 = Auto-calculate (might give odd number)
     1920×1080 → scale=-1:720 → 1280×720 ✅ (lucky, 1280 is even)
     1366×768  → scale=-1:720 → 1279×720 ❌ (odd number - codec error!)

-2 = Auto-calculate AND round to nearest even number
     1366×768  → scale=-2:720 → 1280×720 ✅ (rounded 1279→1280)
```

**Why even numbers matter:**
- H.264 codec uses **macroblocks** (16×16 pixel chunks)
- Dimensions MUST be divisible by 2 (preferably 16)
- Odd dimensions cause encoding errors!

---

## ffmpeg Command Breakdown

```bash
ffmpeg \
  -i input.mp4 \                    # Input file
  -vf "scale=-2:720" \              # Video filter: scale to 720p
  -c:v libx264 \                    # Video codec: H.264
  -preset medium \                  # Speed vs quality tradeoff
  -crf 23 \                         # Quality: 18-28 (lower=better)
  -c:a aac \                        # Audio codec: AAC
  -b:a 128k \                       # Audio bitrate: 128 kbps
  -movflags +faststart \            # Web optimization
  -progress pipe:1 \                # Progress to stdout
  -y \                              # Overwrite output
  output_720p.mp4
```

### Key Parameters Explained:

**1. `-preset medium`**
```
Encoding Speed          Quality          Use Case
────────────────────────────────────────────────────
ultrafast              lowest           Real-time streaming
fast                   low              Quick encoding
medium       ←─────    good      ←────  DEFAULT (balanced)
slow                   better           Archival
veryslow               best             Smallest file size
```

**2. `-crf 23` (Constant Rate Factor)**
```
CRF Value    Quality              File Size
──────────────────────────────────────────────
18           Visually lossless    Large
23           Default (excellent)  Medium  ←── We use this
28           Acceptable           Small
35           Poor                 Very small

Lower = Better quality, larger file
```

**3. `-movflags +faststart`**
```
Without faststart:               With faststart:
┌────────────────┐              ┌────────────────┐
│  Video Data    │              │  Metadata      │ ← Moved to front
│  Audio Data    │              │  Video Data    │
│  Metadata      │ ← At end     │  Audio Data    │
└────────────────┘              └────────────────┘

❌ Browser must download entire    ✅ Browser can start playing
   file to find metadata              immediately (streaming!)
```

---

## `-progress pipe:1` - Real-Time Monitoring

**What it outputs (every second):**
```
frame=150              # Frames processed so far
fps=30.5               # Encoding speed (frames per second)
total_size=1234567     # Output file size (bytes)
out_time_us=5000000    # Current timestamp (microseconds)
out_time=00:00:05.00   # Current timestamp (human readable)
dup_frames=0           # Duplicate frames
drop_frames=0          # Dropped frames
speed=1.2x             # Encoding speed vs realtime
progress=continue      # Status (continue/end)
```

**Example Progress Over Time:**
```
[Second 1]  frame=30   fps=30.0  time=00:00:01.00  speed=1.0x  (starting up)
[Second 5]  frame=150  fps=30.5  time=00:00:05.00  speed=1.2x  (warming up)
[Second 30] frame=900  fps=32.1  time=00:00:30.00  speed=1.5x  (full speed!)
```

**How to parse it in Python:**
```python
process = subprocess.Popen(
    ["ffmpeg", "-i", "input.mp4", "-progress", "pipe:1", "output.mp4"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

for line in process.stdout:
    if line.startswith("frame="):
        current_frame = int(line.split("=")[1])
        percent = (current_frame / total_frames) * 100
        print(f"Progress: {percent:.1f}%")
```

---

## Quality Comparison

**Original (1080p):**
```
Resolution: 1920×1080 = 2,073,600 pixels/frame
Bitrate:    5 Mbps
File size:  150 MB (5 min video)
Bandwidth:  5 Mbps needed to stream
```

**Transcoded (720p):**
```
Resolution: 1280×720 = 921,600 pixels/frame (44% fewer)
Bitrate:    2.5 Mbps (automatic adjustment based on CRF)
File size:  60 MB (60% reduction!)
Bandwidth:  2.5 Mbps needed (works on slower connections)
```

---

## When Scaling Goes Wrong

**1. Upscaling (Bad Idea)**
```
720p → 1080p = Adding pixels that don't exist
Result: Blurry, artificial-looking video
```

**2. Non-Proportional Scaling**
```
16:9 (1920×1080) → 4:3 (1024×768)
Result: Squished or stretched video
```

**3. Odd Dimensions**
```
scale=1279:720
Error: "width not divisible by 2"
Fix: Use scale=-2:720
```

---

## Why We Need Separate Workers

**Architecture:**
```
┌─────────────────────────────────────────────────┐
│  Worker 1: Metadata Extraction                  │
│  - Fast (5-10 seconds)                          │
│  - Low CPU (just reads file headers)            │
│  - Can run many in parallel                     │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  Worker 2: Transcoding                          │
│  - Slow (1-30 minutes)                          │
│  - High CPU (decodes + scales + encodes)        │
│  - Limited parallelism (CPU bound)              │
└─────────────────────────────────────────────────┘
```

**Benefits:**
- Scale workers independently (10 metadata workers, 2 transcode workers)
- Metadata workers never blocked by slow transcoding
- Can prioritize transcode jobs separately
