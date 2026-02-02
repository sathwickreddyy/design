# Multipart Upload with Resumable Sessions

Learn how to implement production-grade file uploads that are **fast**, **reliable**, and **resumable**.

## What You'll Learn

1. **Multipart Upload** - Split large files into chunks and upload in parallel
2. **Upload Sessions** - Track progress in a database to enable resumability
3. **Parallel Throughput** - Achieve 3-5x faster uploads vs sequential
4. **Failure Recovery** - Resume from exact point of failure, not from scratch

## Concepts Explained

### Problem: Large File Uploads Are Fragile

```
Sequential Upload (Old Way):
Client ----[====100MB====]----> Server
               ↓ Network failure at 90%
            START OVER! 😭
```

### Solution: Multipart Upload with Sessions

```
1. Init Session:
   Client -> POST /upload/init -> Server
   Server creates session_id, stores metadata in DB
   
2. Upload Parts in Parallel:
   Client splits file into chunks (5MB each)
   
   Part 1 [5MB] -----> PUT /upload/{session_id}/part/1 -> Server
   Part 2 [5MB] -----> PUT /upload/{session_id}/part/2 -> Server
   Part 3 [5MB] -----> PUT /upload/{session_id}/part/3 -> Server
   (All happening simultaneously)
   
   Server stores each part in /tmp/uploads/{session_id}/part_N
   Updates DB: completed_parts = [1, 2, 3]
   
3. Network Fails at Part 15:
   Client checks: GET /upload/{session_id}/status
   Server responds: "Completed parts: [1,2,3,4,5,6,7,8,9,10,11,12,13,14]"
   Client resumes from part 15 (not from scratch!)
   
4. Complete Upload:
   Client -> POST /upload/{session_id}/complete
   Server assembles all parts into final file
   Cleans up temp parts
```

## Architecture

```
┌─────────────┐
│   Client    │
│  (Python)   │
└──────┬──────┘
       │ 1. POST /upload/init (filename, size)
       ↓
┌─────────────────────────────────┐
│     FastAPI Server              │
│  ┌──────────────────────────┐  │
│  │ Upload Session Manager   │  │
│  └────────┬─────────────────┘  │
│           ↓                     │
│  ┌──────────────────────────┐  │
│  │     PostgreSQL           │  │
│  │  upload_sessions table   │  │
│  │  - session_id            │  │
│  │  - filename              │  │
│  │  - total_parts           │  │
│  │  - completed_parts[]     │  │
│  │  - status                │  │
│  └──────────────────────────┘  │
│           ↓                     │
│  ┌──────────────────────────┐  │
│  │   File Storage           │  │
│  │  /tmp/uploads/{sid}/     │  │
│  │  /data/completed/        │  │
│  └──────────────────────────┘  │
└─────────────────────────────────┘
```

## Key Design Decisions

### 1. Chunk Size: 5MB
- Small enough: Low memory usage, granular resume points
- Large enough: Not too many HTTP requests, reasonable overhead
- Production: AWS S3 uses 5MB-5GB per part

### 2. Parallel Workers: 4 concurrent uploads
- Balance: Network bandwidth vs server capacity
- Too many: Overwhelm server, diminishing returns
- Too few: Underutilize bandwidth

### 3. Database-Backed Sessions
- Survives server restarts
- Multiple clients can check status
- Enables cleanup of abandoned uploads

### 4. Idempotent Part Uploads
- Same part uploaded twice? Overwrite without error
- Critical for retry logic

## API Endpoints

### Initialize Upload
```bash
POST /upload/init
Body: {"filename": "video.mp4", "file_size": 104857600, "chunk_size": 5242880}
Response: {"session_id": "abc123", "total_parts": 20}
```

### Upload Part
```bash
PUT /upload/{session_id}/part/{part_number}
Body: <binary chunk data>
Response: {"part_number": 1, "received": true}
```

### Check Status
```bash
GET /upload/{session_id}/status
Response: {
  "session_id": "abc123",
  "filename": "video.mp4",
  "total_parts": 20,
  "completed_parts": [1, 2, 3, 5, 7],
  "status": "in_progress"
}
```

### Complete Upload
```bash
POST /upload/{session_id}/complete
Response: {"status": "completed", "file_path": "/data/completed/video.mp4"}
```

## Usage

### Start Infrastructure
```bash
cd multipart-upload
docker-compose up -d
```

### Run Upload Demo
```bash
# Create a test file (100MB)
dd if=/dev/urandom of=/tmp/testfile.bin bs=1M count=100

# Run the uploader
python client/uploader.py /tmp/testfile.bin
```

### Simulate Network Failure & Resume
```bash
# Upload will fail partway through
python client/test_upload.py --simulate-failure

# Resume the upload
python client/test_upload.py --resume {session_id}
```

## Learning Exercises

1. **Experiment with Chunk Sizes**
   - Try 1MB, 5MB, 10MB chunks
   - Measure upload time differences
   - Observe memory usage

2. **Test Parallel Workers**
   - Change from 4 to 1, 2, 8, 16 workers
   - When do you hit diminishing returns?

3. **Simulate Failures**
   - Kill server mid-upload, restart, resume
   - Kill client mid-upload, restart, resume
   - What happens if you upload the same part twice?

4. **Add Checksums**
   - Calculate MD5/SHA256 for each part
   - Verify integrity server-side
   - Reject corrupted parts

5. **Cleanup Strategy**
   - What happens to abandoned uploads?
   - Add a background task to clean up old sessions
   - TTL policy: Delete after 24 hours?

## Comparison: Sequential vs Multipart

### Sequential Upload (100MB file, 10Mbps connection)
```
Time: 80 seconds
Failure at 90%: Start over, total time = 160 seconds
```

### Multipart Upload (4 parallel workers)
```
Time: ~25 seconds (3-4x faster)
Failure at 90%: Resume remaining 10%, total time = 30 seconds
```

## Production Considerations

✅ **What This Demo Covers:**
- Parallel chunk uploads
- Session-based resumability
- Database-backed state
- Idempotent part uploads

⚠️ **What Production Needs (Beyond This Demo):**
- Object storage (S3, GCS) instead of local filesystem
- Part checksums/ETags for integrity
- Presigned URLs for direct-to-S3 uploads
- Rate limiting per session
- Authentication/authorization
- Cleanup jobs for abandoned uploads
- Monitoring/metrics (upload success rate, avg time)
- CDN/edge caching for download

## Related Concepts

- **Chunked Transfer Encoding (HTTP)**: Stream unknown-size data
- **AWS S3 Multipart Upload**: Native API, up to 10,000 parts
- **Resumable Upload (Google)**: Single upload URL, range requests
- **BitTorrent**: Peer-to-peer multipart distribution

## References

- [AWS S3 Multipart Upload](https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuoverview.html)
- [Google Resumable Upload](https://cloud.google.com/storage/docs/resumable-uploads)
- [RFC 7233 - Range Requests](https://tools.ietf.org/html/rfc7233)
