# Sync Conflict Resolver

File sync system demonstrating **Optimistic Concurrency Control** with **Object Storage Architecture** for conflict detection and resolution.

## 🎯 What This Demonstrates

- **Offline Conflict:** Two clients edit while disconnected, then sync
- **Online Conflict:** Two clients edit simultaneously (race condition)
- **Optimistic Locking:** Version-based conflict detection (no row locks!)
- **Resolution Strategy:** Keep-both (conflicted copies)
- **Production Architecture:** Metadata in Postgres, content in MinIO (S3-compatible)

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   SYNC SERVER (FastAPI)                      │
│  ┌────────────────┐              ┌─────────────────┐        │
│  │ PostgreSQL     │              │ MinIO (S3)      │        │
│  │ (Metadata)     │              │ (File Content)  │        │
│  │ - file_id      │              │ - Actual bytes  │        │
│  │ - version      │◄──points to──┤ - Versioned     │        │
│  │ - storage_key  │              │ - Scalable      │        │
│  │ - content_hash │              │ - CDN-ready     │        │
│  └────────────────┘              └─────────────────┘        │
│  Optimistic locking:                                         │
│  UPDATE WHERE version = expected (atomic, no locks!)         │
└──────────────────────────────────────────────────────────────┘
                         ▲        ▲
                         │        │
           ┌─────────────┘        └─────────────┐
           │                                     │
┌──────────┴───────────┐           ┌────────────┴─────────────┐
│   CLIENT A           │           │   CLIENT B               │
│  - Local file cache  │           │  - Local file cache      │
│  - Version tracking  │           │  - Version tracking      │
│  - Conflict handler  │           │  - Conflict handler      │
└──────────────────────┘           └──────────────────────────┘
```

## 📁 Project Structure

```
google-drive/
├── src/
│   ├── core/
│   │   ├── config.py          # Settings & environment
│   │   └── database.py        # Database connection
│   ├── models/
│   │   └── database.py        # SQLAlchemy models
│   ├── schemas/
│   │   └── file.py            # Pydantic schemas
│   ├── services/
│   │   ├── storage.py         # MinIO operations
│   │   └── file_sync.py       # Business logic
│   ├── api/
│   │   └── endpoints.py       # FastAPI routes
│   └── main.py                # Application entry point
├── demo_offline.py            # Offline conflict demo
├── demo_online.py             # Online conflict demo
├── sync_client.py             # Client library
├── docker-compose.yml         # Postgres + MinIO
└── requirements.txt           # Dependencies
```

## 🚀 Setup & Run

### 1. Prerequisites

```bash
# Ensure observability-net exists (external Docker network)
docker network create observability-net 2>/dev/null || true
```

### 2. Start Services (PostgreSQL + MinIO)

```bash
docker-compose up -d
```

Wait for services to be ready:
```bash
docker-compose logs -f
# Wait for "database system is ready" and MinIO health check
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Start Sync Server

```bash
python -m src.main
# Or with uvicorn directly:
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Access Services

- **API Server:** http://localhost:8000
- **API Docs (Swagger):** http://localhost:8000/docs
- **MinIO Console:** http://localhost:9001 (user: `minioadmin`, password: `minioadmin`)

## 📝 API Endpoints

### File Upload (Real endpoint for users)

**POST /files/upload** - Upload actual files
```bash
curl -X POST "http://localhost:8000/files/upload" \
  -F "file=@document.pdf" \
  -F "file_id=docs/document.pdf" \
  -F "expected_version=0"
```

- `file`: The actual file to upload (multipart/form-data)
- `file_id`: Unique identifier (like a path: "docs/report.txt")
- `expected_version`: 0 for new files, current version for updates

**Response:**
```json
{
  "status": "created",
  "file_id": "docs/document.pdf",
  "version": 1,
  "content_hash": "abc123...",
  "storage_key": "abc12345/docs/document.pdf/v1",
  "size_bytes": 102400
}
```

### Other Endpoints

- **GET /files/** - List all files
- **GET /files/{file_id}/metadata** - Get metadata only
- **GET /files/{file_id}/download** - Download file (binary streaming)
- **GET /files/{file_id}** - Get as text (for demo)
- **POST /files/{file_id}** - Upload text content (legacy/demo)
- **DELETE /files/{file_id}** - Delete file

## 🧪 Run Conflict Demos

### Offline Conflict

```bash
python demo_offline.py

```bash
python sync_server.py
```

Server runs at: `http://localhost:8000`  
API docs: `http://localhost:8000/docs`

### 5. Run Demos (in separate terminals)

**Offline Conflict:**
```bash
python demo_offline.py
```

**Online Conflict:**
```bash
python demo_online.py
```

## 📊 What You'll See

### Offline Conflict Demo Output

```
🎬 OFFLINE CONFLICT SCENARIO DEMO
======================================================================

📝 STEP 1: Client A creates initial file
----------------------------------------------------------------------
✅ [ClientA] Created document.txt v1

📥 STEP 2: Both clients download the file (v1)
----------------------------------------------------------------------
✅ [ClientA] Downloaded document.txt v1: "Hello World - Version 1"
✅ [ClientB] Downloaded document.txt v1: "Hello World - Version 1"

💤 STEP 3: BOTH CLIENTS GO OFFLINE
----------------------------------------------------------------------
⚠️  Network disconnected - clients working independently

✏️ STEP 4: Client A edits file (offline)
----------------------------------------------------------------------
✏️ [ClientA] Edited document.txt:
   Old: "Hello World - Version 1"
   New: "Hello World - EDITED BY CLIENT A (offline)"

✏️ STEP 5: Client B edits file (offline)
----------------------------------------------------------------------
✏️ [ClientB] Edited document.txt:
   Old: "Hello World - Version 1"
   New: "Hello World - EDITED BY CLIENT B (offline)"

📤 STEP 7: Client A syncs first
----------------------------------------------------------------------
✅ [ClientA] Upload successful: document.txt v1 → v2

📤 STEP 8: Client B tries to sync (CONFLICT!)
----------------------------------------------------------------------
⚠️ [ClientB] CONFLICT detected for document.txt!
   Expected version: 1
   Server version: 2

🔧 STEP 9: Resolving conflict (KEEP BOTH strategy)
----------------------------------------------------------------------
✅ [ClientB] Conflict resolved:
   - document.txt: accepted server version v2
   - document (conflicted copy ClientB).txt: saved local changes
```

### Online Conflict Demo Output

```
🎬 ONLINE CONFLICT SCENARIO DEMO
======================================================================

⚡ STEP 4: RACE CONDITION - Both sync at nearly same time
----------------------------------------------------------------------
📤 Both clients racing to upload their changes...

📊 RACE RESULTS
======================================================================

🏆 Winner: Client A
   • Upload succeeded (v1 → v2)
   • Content: "PYTHON is the best language!"

❌ Loser: Client B
   • Upload rejected (version conflict)
   • Reason: Server version already updated to v2
```

## 🔑 Key Concepts

### Optimistic Locking

```python
# Client sends expected version
POST /files/doc.txt
{
  "content": "new content",
  "expected_version": 5
}

# Server checks atomically
if current_version != expected_version:
    return 409 CONFLICT
else:
    version += 1
    save()
```

### Conflict Detection

| Scenario | Detection | Resolution |
|----------|-----------|-----------|
| **Offline** | Version mismatch after reconnect | Keep both (conflicted copy) |
| **Online** | Atomic version check fails | First-write-wins + retry |

### Why Version Numbers?

- ✅ Simple to implement
- ✅ No clock synchronization needed
- ✅ Deterministic ordering
- ✅ Easy to explain in interviews

## 🛠️ API Endpoints

### Create/Upload File
```http
POST /files/{file_id}
Content-Type: application/json

{
  "content": "file content",
  "expected_version": 1,
  "content_hash": "sha256..."
}
```

**Responses:**
- `200 OK` - Success
- `409 CONFLICT` - Version mismatch
- `400 Bad Request` - Hash mismatch

### Download File
```http
GET /files/{file_id}
```

**Response:**
```json
{
  "file_id": "doc.txt",
  "content": "file content",
  "version": 2,
  "content_hash": "abc123...",
  "updated_at": "2026-02-05T10:30:00"
}
```

### List Files
```http
GET /files
```

## 🧪 Testing Manually

### Create a file
```bash
curl -X POST http://localhost:8000/files/test.txt \
  -H "Content-Type: application/json" \
  -d '{
    "content": "initial content",
    "expected_version": 0
  }'
```

### Update with correct version
```bash
curl -X POST http://localhost:8000/files/test.txt \
  -H "Content-Type: application/json" \
  -d '{
    "content": "updated content",
    "expected_version": 1
  }'
```

### Trigger conflict (wrong version)
```bash
curl -X POST http://localhost:8000/files/test.txt \
  -H "Content-Type: application/json" \
  -d '{
    "content": "conflicting content",
    "expected_version": 1
  }'
# Returns 409 CONFLICT
```

## 🧹 Cleanup

```bash
# Stop and remove containers
docker-compose down

# Remove volumes (deletes database)
docker-compose down -v
```

## 📝 Logging

All operations are logged with structured output:

```
INFO - sync_server - 📤 POST /files/doc.txt (expected_version=1)
INFO - sync_server - ✅ Updated doc.txt: v1 → v2
INFO - Client_A - ✅ [ClientA] Upload successful: doc.txt v1 → v2
INFO - Client_B - ⚠️ [ClientB] CONFLICT detected for doc.txt!
```

**Splunk Query Examples:**

```spl
# Find all conflicts
index=sync source=sync_server "CONFLICT detected"
| stats count by file_id, client_id

# Track file version history
index=sync source=sync_server "Updated"
| rex field=_raw "Updated (?<file_id>\S+): v(?<old_version>\d+) → v(?<new_version>\d+)"
| table _time, file_id, old_version, new_version
```

## 🎓 Interview Talking Points

1. **Why optimistic locking?**
   - No distributed coordination needed
   - Better performance (no locks held)
   - Simple to understand and implement

2. **Why version numbers over timestamps?**
   - Clock skew problems eliminated
   - Deterministic ordering
   - Easier to reason about

3. **Future enhancements:**
   - 3-way merge for text files
   - Version vectors for multi-master sync
   - CRDT for real-time collaboration
   - Chunked uploads for large files

## 📚 System Design Context

This demonstrates a **simplified Google Drive/Dropbox sync** model:

- ✅ Client-server architecture
- ✅ Optimistic concurrency control
- ✅ Conflict detection & resolution
- ✅ Version tracking
- ✅ Content integrity (hashing)

**Not covered (out of scope):**
- File chunking/streaming
- Delta sync (rsync-style)
- Folder hierarchies
- Permissions/ACLs
- Real-time collaboration (CRDT/OT)
