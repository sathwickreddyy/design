# Multipart Upload with Checksum Verification

**Interview Prep**: Production-grade file upload system with parallel uploads, resumability, and two-level integrity verification.

---

## Core Problem & Solution

### Problem: Large File Uploads Fail
- **Network instability** → 90% uploaded, network drops → start over from 0%
- **Sequential uploads** → Underutilize bandwidth → slow
- **No integrity checks** → Silent corruption → discover weeks later

### Solution: Multipart Upload
```
100 MB file → Split into 20 × 5MB parts → Upload in parallel (4 workers)
Result: 15x faster + resumable + verified integrity
```

---

## System Architecture

```
CLIENT                     SERVER                    DATABASE
━━━━━━                    ━━━━━━━━━━                ━━━━━━━━━━━━

1. Init Phase
   Calculate SHA256 ───→  Store session       ───→  upload_sessions
   of file                + file_hash                 - session_id
                                                      - file_hash
                                                      - total_parts: 20
                                                      
2. Upload Phase (Parallel)
   Part 1 + MD5 ──────→   Verify MD5         ───→  completed_parts: [1]
   Part 2 + MD5 ──────→   Verify MD5         ───→  completed_parts: [1,2]
   Part 3 + MD5 ──────→   Verify MD5         ───→  completed_parts: [1,2,3]
   Part 4 + MD5 ──────→   Verify MD5         ───→  completed_parts: [1,2,3,4]
   (4 concurrent uploads)
   
3. Complete Phase
   Complete ──────────→   Assemble parts     ───→  status: "completed"
                         Calculate SHA256
                         Verify matches!
```

**Key Components:**
- **PostgreSQL**: Session state, checksums, atomic updates
- **FastAPI**: REST endpoints, checksum verification
- **Local FS**: Temp parts (`/tmp/uploads/{id}/part_N`) + final file (`/data/completed/`)

---

## Interview Topics Covered

### 1. Parallelism & Throughput

**Q: Why parallel uploads?**
- Sequential: 100MB ÷ 1.25MB/s = 80 seconds
- Parallel (4 workers): 100MB ÷ 5MB/s = 20 seconds
- **4x throughput increase**

**Implementation:**
```python
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(upload_part, part_num, data): part_num 
               for part_num, data in parts}
```

**Tradeoff:** More workers = faster, but diminishing returns after 4-8 (server bottleneck).

---

### 2. Resumability & State Management

**Q: How to resume after network failure?**

**Without sessions:** Start over (upload 100MB again)  
**With sessions:** Query `completed_parts`, upload only missing parts

```sql
SELECT completed_parts FROM upload_sessions WHERE session_id = ?
-- Returns: [1, 2, 3, 5, 7] → Resume from parts 4, 6, 8...
```

**Key insight:** Database-backed state survives server restarts.

---

### 3. Race Conditions & Atomicity

**Q: What happens when 4 workers upload parts simultaneously?**

**Problem:** Non-atomic array append
```python
# BAD: Race condition
if part_num not in session.completed_parts:
    session.completed_parts.append(part_num)  # Lost updates!
```

**Solution:** SQL-level atomic operation
```sql
UPDATE upload_sessions
SET completed_parts = array_append(completed_parts, :part_num)
WHERE session_id = :sid 
  AND NOT :part_num = ANY(completed_parts);  -- Idempotent
```

**Interview answer:** Use database transaction isolation or SQL atomic operations for concurrent writes.

---

### 4. Data Integrity (Two-Level Checksums)

**Q: How to detect corruption?**

**Level 1: Per-Part MD5** (Fast, catches transport errors)
```
Client: Calculate MD5 of 5MB chunk → Send in X-Part-Hash header
Server: Verify MD5 on receipt → Reject if mismatch → Client retries
```

**Level 2: Full-File SHA256** (Secure, catches assembly bugs)
```
Client: Calculate SHA256 of entire file before split
Server: After assembly, calculate SHA256 → Compare with original
```

**Why two levels?**
- MD5 is fast (5ms per 5MB), catches 99.9% of transport errors
- SHA256 is slower (100ms per 100MB), cryptographically secure, catches assembly bugs

**Without checksums:** Silent corruption discovered weeks later during file use  
**With checksums:** Corruption detected in seconds, automatic retry

---

### 5. Idempotency

**Q: What if the same part is uploaded twice?**

**Design principle:** Uploading part N multiple times = same result

**Implementation:**
- Overwrite existing `part_N` file
- SQL: `AND NOT :part_num = ANY(completed_parts)` → No duplicate array entries
- Server returns same checksum every time

**Why critical:** Network retries must be safe (no duplicate data).

---

## API Design

### Endpoint 1: Initialize Upload
```http
POST /upload/init
Content-Type: application/json

{
  "filename": "video.mp4",
  "file_size": 104857600,
  "file_hash": "a7b3c2...",  ← SHA256 of full file
  "chunk_size": 5242880
}

Response:
{
  "session_id": "uuid-123",
  "total_parts": 20
}
```

### Endpoint 2: Upload Part
```http
PUT /upload/{session_id}/part/{part_number}
X-Part-Hash: md5_hex_string  ← MD5 of this 5MB part
Content-Type: application/octet-stream

<binary chunk data>

Response:
{
  "part_number": 1,
  "received": true,
  "checksum": "md5_hex"  ← Server-calculated MD5
}
```

### Endpoint 3: Check Status (Resume Support)
```http
GET /upload/{session_id}/status

Response:
{
  "completed_parts": [1, 2, 3, 5, 7],  ← Missing: 4, 6, 8...
  "total_parts": 20,
  "progress_percent": 35.0,
  "status": "in_progress"
}
```

### Endpoint 4: Complete Upload
```http
POST /upload/{session_id}/complete

Server:
1. Check all parts present
2. Assemble parts in order: [1, 2, 3, ..., 20]
3. Calculate SHA256 of assembled file
4. Verify matches original file_hash
5. If mismatch → 400 "File integrity check failed"

Response:
{
  "status": "completed",
  "file_path": "/data/completed/video.mp4"
}
```

---

## Database Schema

```sql
CREATE TABLE upload_sessions (
    session_id         VARCHAR(64) PRIMARY KEY,
    filename           VARCHAR(512) NOT NULL,
    file_size          BIGINT NOT NULL,
    chunk_size         INTEGER NOT NULL DEFAULT 5242880,
    total_parts        INTEGER NOT NULL,
    
    -- Progress tracking
    completed_parts    INTEGER[] DEFAULT '{}',  -- [1, 2, 5, 7]
    
    -- Integrity verification
    file_hash          VARCHAR(64),             -- SHA256 of full file
    hash_algorithm     VARCHAR(20) DEFAULT 'SHA256',
    part_hashes        JSONB DEFAULT '{}',      -- {"1": "md5", "2": "md5"}
    
    -- State
    status             VARCHAR(20) DEFAULT 'in_progress',  -- completed/failed
    created_at         TIMESTAMP DEFAULT NOW(),
    completed_at       TIMESTAMP
);

CREATE INDEX idx_status ON upload_sessions(status);
CREATE INDEX idx_created ON upload_sessions(created_at);
```

**Interview insight:** JSONB for part_hashes allows flexible querying (e.g., find missing hashes).

---

## Key Interview Questions & Answers

### Q1: Why 5MB chunk size?
**A:** Balance between:
- Too small (1MB): Too many HTTP requests (overhead), but granular resume
- Too large (50MB): Few requests (good), but coarse resume, high memory
- 5MB: Sweet spot (AWS S3 uses 5MB-5GB range)

### Q2: How to handle server restart mid-upload?
**A:** Database-backed sessions persist state:
```
1. Server crashes after 12/20 parts uploaded
2. Client queries: GET /upload/{id}/status
3. Server reads from DB: completed_parts = [1..12]
4. Client resumes from part 13
```

### Q3: Race condition with parallel uploads?
**A:** Use SQL atomic operations:
```sql
-- Single atomic transaction per part upload
UPDATE upload_sessions
SET completed_parts = array_append(completed_parts, 5)
WHERE session_id = 'abc' AND NOT 5 = ANY(completed_parts);
```
**Why not Python?** Python-level checks are non-atomic across requests.

### Q4: How to detect corrupted data?
**A:** Two-level verification:
1. **MD5 per part**: Client sends `X-Part-Hash`, server verifies immediately
2. **SHA256 full file**: After assembly, server verifies entire file

**Catches:**
- Network bit flips (Level 1)
- Assembly bugs (Level 2)
- Disk errors (Level 2)

### Q5: What if part hash mismatches?
**A:**
```
Server returns: 400 "Checksum mismatch for part 5"
Client: Automatic retry of part 5
Result: Self-healing upload
```

### Q6: Tradeoffs vs direct S3 upload?
**A:**

| Aspect | This System | Direct S3 |
|--------|------------|-----------|
| **Control** | Full control | S3 API limits |
| **Cost** | Server + storage | S3 pricing |
| **Durability** | Single server | 99.999999999% |
| **Scale** | Manual scale | Auto-scale |
| **Use case** | Learning, custom logic | Production at scale |

---

## Performance Metrics

**Test: 100 MB file @ 10 Mbps (1.25 MB/s)**

| Metric | Sequential | Multipart (4 workers) |
|--------|------------|----------------------|
| Upload time | 80s | ~20s |
| Network failure at 90% | Start over (160s total) | Resume 10% (25s total) |
| Throughput | 1.25 MB/s | 5 MB/s |
| **Speedup** | 1x | **4x** |

**Checksum overhead:** ~200ms (0.25% of upload time)

---

## Testing

```bash
# Start system
docker-compose up -d

# Run comprehensive tests
python client/test_upload.py

Tests:
✓ Normal upload (20 MB, 4 parts)
✓ Resume after simulated failure (50 MB, 6/10 → 10/10 parts)
✓ Status queries during upload
✓ Session listing
```

---

## Production Considerations

**What's implemented (MVP):**
- ✅ Parallel uploads with ThreadPoolExecutor
- ✅ Database-backed resumability
- ✅ MD5 per-part + SHA256 full-file verification
- ✅ Atomic array updates (race-condition safe)
- ✅ Idempotent part uploads
- ✅ REST API with FastAPI

**What production needs:**
- ⚠️ Object storage (S3/GCS) instead of local filesystem
- ⚠️ Presigned URLs (direct client → S3, bypass server)
- ⚠️ Authentication & authorization (JWT, OAuth)
- ⚠️ Rate limiting (per user, per session)
- ⚠️ Cleanup job (delete abandoned sessions after 24h)
- ⚠️ Monitoring (upload success rate, latency, errors)
- ⚠️ CDN for downloads (CloudFront, Fastly)

---

## Related System Design Patterns

1. **S3 Multipart Upload**: AWS's native implementation (up to 10,000 parts)
2. **Google Resumable Upload**: Single URL, range requests
3. **BitTorrent**: P2P chunk distribution with piece verification
4. **Content-Addressable Storage**: Use content hash as filename (deduplication)
5. **Erasure Coding**: Parity parts for self-healing (RAID-like)

---

## Quick Reference

```bash
# Client usage
python client/uploader.py /path/to/file.bin

# Resume upload
python client/uploader.py /path/to/file.bin --resume <session_id>

# Run tests
python client/test_upload.py
```

**Files:**
- `app/main.py` - FastAPI server with checksum verification
- `app/models.py` - SQLAlchemy ORM (upload_sessions table)
- `client/uploader.py` - Multipart upload client with parallel workers
- `init_db.sql` - Database schema

**Stack:** Python 3.11 + FastAPI + PostgreSQL + SQLAlchemy
