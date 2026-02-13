# Database Sharding - Google Drive System

## 🎯 Core Problem: Why Shard?

```
Single DB Limits:
├── Storage: ~10TB per instance
├── Throughput: ~100K QPS
├── Users: ~10M active users
└── Files: ~100M total files

Google Drive Scale:
├── Users: 1B+
├── Files: 100B+
└── Need: Horizontal scaling
```

---

## 1️⃣ UUID over Auto-Increment

### Why Sequential IDs Fail at Scale

```
Auto-increment (Single DB):
INSERT INTO files → id=1, id=2, id=3...
└─ Works fine

Auto-increment (Sharded):
┌─────────┐  ┌─────────┐  ┌─────────┐
│ Shard 0 │  │ Shard 1 │  │ Shard 2 │
│ id=1    │  │ id=1    │  │ id=1    │ ← Collision!
└─────────┘  └─────────┘  └─────────┘

Solution: UUID (globally unique)
id = "550e8400-e29b-41d4-a716-446655440000"
```

---

## 2️⃣ Multi-User Sharding Strategy

### Shard Key: user_id (Google Drive Approach)

```
User A's files:
┌──────────────────┐
│ user_id: alice   │
│ ├── My Drive     │
│ ├── Documents    │
│ └── report.pdf   │
└──────────────────┘
      ↓
hash(alice) % 8 → Shard 0

User B's files:
┌──────────────────┐
│ user_id: bob     │
│ ├── My Drive     │
│ └── Work         │
└──────────────────┘
      ↓
hash(bob) % 8 → Shard 3

Result: Each user's data on ONE shard
```

**Why user_id?**
- ✅ User isolation (security boundary)
- ✅ Quota enforcement per shard
- ✅ All user operations = single shard query
- ✅ Analytics per user shard

**Trade-off:**
- ❌ Celebrity user (1M files) = hot shard
- ❌ Shared folders = cross-shard queries

---

## 3️⃣ Modulo vs Consistent Hashing

### ❌ Modulo Problem: Adding Shards

```
Initial (3 shards):
Alice: hash(alice) % 3 = 0 → Shard 0
Bob:   hash(bob)   % 3 = 1 → Shard 1
Carol: hash(carol) % 3 = 2 → Shard 2

Add 4th shard:
Alice: hash(alice) % 4 = 2 → Shard 2 (MOVED!)
Bob:   hash(bob)   % 4 = 1 → Shard 1 (same)
Carol: hash(carol) % 4 = 0 → Shard 0 (MOVED!)

Result: 67% data migration! ❌
```

### ✅ Consistent Hashing: Minimal Migration

```
Hash Ring (0-360):
    0°
  ┌───┐
3 │   │ 1   Shard positions:
  │   │     - Shard A: 30°
2 └───┘     - Shard B: 150°
             - Shard C: 270°

User placement (clockwise):
Alice (hash=50°)  → Shard B (next position)
Bob   (hash=200°) → Shard C
Carol (hash=300°) → Shard A

Add Shard D at 100°:
Alice (50°)  → Shard D (NEW, only nearby affected)
Bob   (200°) → Shard C (no change)
Carol (300°) → Shard A (no change)

Result: Only 33% migrates! ✅
```

### Interview Key Point

| Aspect | Modulo | Consistent Hashing |
|--------|--------|-------------------|
| Add shard | 67% migration | 5-10% migration |
| Remove shard | 50% migration | 10-15% migration |
| Complexity | 1 line | ~50 lines |
| When to use | Fixed shards | Dynamic scaling |

---

## 4️⃣ Real-World: Google Drive Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────┐
│           Application Layer (API)               │
│  ┌──────────────────────────────────────────┐  │
│  │   Consistent Hash Router                  │  │
│  │   hash(user_id) → ring position → shard  │  │
│  └──────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│         Metadata Storage (Colossus-like)        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Shard 0  │  │ Shard 1  │  │ Shard 2  │     │
│  │ Users:   │  │ Users:   │  │ Users:   │     │
│  │ alice    │  │ bob      │  │ carol    │     │
│  │ dave     │  │ eve      │  │ frank    │     │
│  └──────────┘  └──────────┘  └──────────┘     │
│  Each shard: 10-50M files                      │
│  Replication: 3x (Paxos consensus)             │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│        File Storage (GCS/S3-like)               │
│  Bucketed by content_hash:                      │
│  gs://files/XX/YY/{hash}                        │
│  - XX = hash[0:2]  (256 prefixes)              │
│  - YY = hash[2:4]  (65,536 total prefixes)     │
└─────────────────────────────────────────────────┘
```

### Query Flow

```python
# List user's files
SELECT * FROM files 
WHERE user_id = 'alice' 
  AND parent_id = 'folder_123'

Execution:
1. Router: hash(alice) → Shard 0
2. Query Shard 0 only ✅
3. No cross-shard joins

# Shared folder (different user)
SELECT * FROM files 
WHERE user_id = 'bob'  # Bob's shard
  AND id IN (shared_folder_ids)  # Might be Alice's shard

Execution:
1. Router: hash(bob) → Shard 1
2. Check shared_links table on Shard 1
3. Cross-shard query to Alice's shard if needed ⚠️
4. Cache frequently accessed shared folders
```

---

## 5️⃣ Schema Design for Multi-User

```python
class FileRecord(Base):
    __tablename__ = "files"
    
    # Primary key (UUID)
    id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True,
        default=lambda: str(uuid4())
    )
    
    # Hierarchy
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), 
        ForeignKey('files.id', ondelete='CASCADE'),
        index=True
    )
    
    # Multi-user: SHARD KEY
    user_id: Mapped[str] = mapped_column(
        String(36), 
        index=True,
        comment="Owner - used as shard key"
    )
    
    # Root tracking (user's "My Drive")
    root_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        comment="Top-level folder for user's drive"
    )
    
    # File metadata
    name: Mapped[str] = mapped_column(String(255))
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Sharing
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    
    @property
    def shard_key(self) -> str:
        """Returns user_id for sharding"""
        return self.user_id
    
    def get_shard_id(self, num_shards: int = 8) -> int:
        """Calculate shard via consistent hashing"""
        import hashlib
        hash_val = int(hashlib.md5(self.user_id.encode()).hexdigest(), 16)
        return hash_val % num_shards


class FileVersionHistory(Base):
    __tablename__ = "file_version_history"
    
    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), 
        index=True,
        comment="Denormalized - keeps history on same shard as file"
    )
    
    # Snapshot
    version: Mapped[int]
    content_hash: Mapped[str]
    size_bytes: Mapped[int]
```

**Key Design Decisions:**
1. **user_id as shard key** - co-locates all user data
2. **Denormalize user_id in history** - avoids cross-shard joins
3. **root_id tracks user's drive** - fast root folder queries

---

## 6️⃣ Consistent Hash Router

```python
from bisect import bisect_right

class ConsistentHashRing:
    def __init__(self, num_shards: int = 8, virtual_nodes: int = 150):
        """
        Virtual nodes: Each shard gets 150 positions on ring
        → Smoother distribution (avoids hot spots)
        """
        self.ring = {}
        self.sorted_keys = []
        
        for shard_id in range(num_shards):
            for vnode in range(virtual_nodes):
                # Create virtual node
                key = f"shard_{shard_id}_vnode_{vnode}"
                hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
                self.ring[hash_val] = shard_id
        
        self.sorted_keys = sorted(self.ring.keys())
    
    def get_shard(self, user_id: str) -> int:
        """Route user to shard via ring position"""
        hash_val = int(hashlib.md5(user_id.encode()).hexdigest(), 16)
        
        # Find next position clockwise
        idx = bisect_right(self.sorted_keys, hash_val)
        if idx == len(self.sorted_keys):
            idx = 0
        
        ring_key = self.sorted_keys[idx]
        return self.ring[ring_key]


class ShardRouter:
    def __init__(self, shard_engines: list[AsyncEngine]):
        self.shards = shard_engines
        self.ring = ConsistentHashRing(num_shards=len(shard_engines))
    
    async def get_engine(self, user_id: str) -> AsyncEngine:
        """Get database engine for user"""
        shard_id = self.ring.get_shard(user_id)
        return self.shards[shard_id]
    
    async def list_user_files(self, user_id: str, parent_id: str):
        """Single-shard query"""
        engine = await self.get_engine(user_id)
        async with engine.begin() as conn:
            result = await conn.execute(
                select(FileRecord)
                .where(FileRecord.user_id == user_id)
                .where(FileRecord.parent_id == parent_id)
            )
            return result.scalars().all()
```

---

## 7️⃣ Interview Cheat Sheet

### Question: "How would you shard Google Drive?"

**Answer Framework:**
```
1. Shard Key: user_id
   - Co-locates all user data
   - Enables quotas, isolation, analytics
   
2. Consistent Hashing
   - Minimal migration when adding shards
   - Virtual nodes for even distribution
   
3. Denormalization
   - user_id in version history
   - Avoids cross-shard joins
   
4. Shared Folders
   - Pointer approach (like Google)
   - Accept cross-shard query trade-off
   - Cache frequently accessed
```

### Common Follow-ups

| Question | Answer |
|----------|--------|
| **Hot user problem?** | Sub-shard by root_id within user's shard |
| **Shared folder query slow?** | Cache shared metadata + lazy load |
| **Adding shards?** | Consistent hashing: only 5-10% migrates |
| **Cross-shard transactions?** | 2PC or Saga pattern (avoid if possible) |
| **Why not parent_id as shard key?** | Multi-user needs user isolation |

### Complexity Analysis

| Operation | Single DB | Sharded (user_id) |
|-----------|-----------|-------------------|
| List user files | O(log n) | O(log n) - same shard |
| Upload file | O(1) | O(1) - same shard |
| Shared folder read | O(log n) | O(2 log n) - cross-shard |
| Add shard | N/A | O(n/10) - 10% migration |

---

## 8️⃣ Production Checklist

```
✅ Use UUID for IDs (no auto-increment)
✅ Shard by user_id (multi-user isolation)
✅ Consistent hashing (dynamic scaling)
✅ Denormalize shard key in related tables
✅ Virtual nodes (150+) for even distribution
✅ Monitor shard imbalance
✅ Cache hot users/shared folders
✅ Plan migration strategy before sharding
```
