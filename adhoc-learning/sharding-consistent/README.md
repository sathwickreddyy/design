# Drive Clone - Consistent Hashing Implementation

A demonstration of consistent hashing for database sharding that minimizes data movement when adding/removing shards.

## What is Consistent Hashing?

Unlike modulo-based sharding (`user_id % num_shards`), consistent hashing places both data and servers on the same circular hash space. When you add or remove a server, only the data in that specific portion of the circle needs to move.

**Key Advantage:**
- **Modulo sharding:** Adding 1 shard causes ~66% data movement
- **Consistent hashing:** Adding 1 shard causes ~33% data movement

## Architecture

```
Hash Ring (0 to 2^32-1):

    Virtual Node System:
    - Each physical shard has 150 virtual nodes
    - Virtual nodes distributed evenly around ring
    - Ensures balanced data distribution
    
    Routing:
    1. Hash user_id → position on ring
    2. Go clockwise to next virtual node
    3. Return physical shard that owns that vnode
```

## Quick Start

### 1. Create Docker Network
```bash
docker network create observability-net
```

### 2. Start with 2 Shards
```bash
cd sharding-consistent
docker-compose up --build -d
```

### 3. Insert 1000 Test Records
```bash
curl -X POST "http://localhost:8000/ingest/bulk?count=1000"
```

### 4. Check Initial Distribution
```bash
curl http://localhost:8000/stats | jq
```

### 5. Add 3rd Shard
```bash
# First, start the 3rd shard container
docker-compose --profile with-shard-2 up -d db_shard_2

# Add it to the hash ring
curl -X POST "http://localhost:8000/ring/add_shard/2"
```

### 6. Analyze Migration Impact
```bash
curl "http://localhost:8000/ring/analyze_add/2" | jq
```

## Database Connection Details

### Shard 0
- **Host:** localhost
- **Port:** 5432
- **Database:** drive_shard_0
- **User:** shard_user
- **Password:** shard_pass

### Shard 1
- **Host:** localhost
- **Port:** 5433
- **Database:** drive_shard_1
- **User:** shard_user
- **Password:** shard_pass

### Shard 2
- **Host:** localhost
- **Port:** 5434
- **Database:** drive_shard_2
- **User:** shard_user
- **Password:** shard_pass

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check and ring info |
| `/ingest` | POST | Insert single file record |
| `/ingest/bulk?count=N` | POST | Insert N test records |
| `/stats` | GET | Get distribution & ring state |
| `/query/{user_id}` | GET | Get all files for a user |
| `/ring/state` | GET | Get hash ring configuration |
| `/ring/add_shard/{id}` | POST | Add shard to ring |
| `/ring/analyze_add/{id}` | GET | Predict migration impact |

## Phase 4 Test: Proving 33% vs 66%

### Step 1: Initial Setup (2 Shards, 1000 Records)
```bash
# Start services
docker-compose up --build -d

# Insert 1000 records
curl -X POST "http://localhost:8000/ingest/bulk?count=1000"

# Check distribution
curl http://localhost:8000/stats | jq '.shards'
```

**Expected:** ~500 records per shard (50/50 distribution)

### Step 2: Analyze Adding 3rd Shard (Before Migration)
```bash
curl "http://localhost:8000/ring/analyze_add/2" | jq
```

**Expected Output:**
```json
{
  "event": "redistribution_analysis",
  "current_shards": 2,
  "new_total_shards": 3,
  "sample_size": 10000,
  "keys_that_move": ~3333,
  "keys_that_stay": ~6667,
  "movement_percentage": ~33.33,
  "theoretical_movement": 33.33
}
```

### Step 3: Actually Add 3rd Shard
```bash
# Start shard 2
docker-compose --profile with-shard-2 up -d db_shard_2

# Add to ring
curl -X POST "http://localhost:8000/ring/add_shard/2"
```

### Step 4: Check New Distribution
```bash
curl http://localhost:8000/stats | jq
```

**Expected:** Each shard has ~333 records (33/33/33 distribution)

### Step 5: Run Migration Script
```bash
docker exec drive_consistent_api python3 migrate_consistent.py
```

## Logs for Splunk Visualization

All routing decisions, ring changes, and migrations are logged in structured JSON format:

```json
{
  "event": "routing_decision",
  "key": "user_123",
  "key_hash": 2847563829,
  "next_vnode_position": 2850000000,
  "assigned_shard": 1,
  "total_vnodes_checked": 300
}

{
  "event": "shard_added",
  "shard_id": 2,
  "virtual_nodes": 150,
  "total_ring_size": 450,
  "sample_positions": [123456, 234567, 345678, ...]
}

{
  "event": "redistribution_analysis",
  "movement_percentage": 33.33,
  "keys_that_move": 333,
  "keys_that_stay": 667
}
```

### Splunk Queries

**View ring state changes:**
```
index=* "SPLUNK:" event=shard_added OR event=shard_removed
| table _time shard_id total_ring_size
```

**Analyze routing decisions:**
```
index=* "SPLUNK:" event=routing_decision
| stats count by assigned_shard
| eval percentage = (count / sum(count)) * 100
```

**Track migration impact:**
```
index=* "SPLUNK:" event=redistribution_analysis
| table _time movement_percentage keys_that_move keys_that_stay
```

## Comparison: Modulo vs Consistent Hashing

| Aspect | Modulo (Phase 1-3) | Consistent Hash (Phase 4) |
|--------|-------------------|---------------------------|
| **Data Movement** | 66% when adding 3rd shard | 33% when adding 3rd shard |
| **Distribution** | Perfect (mathematical) | Near-perfect (statistical) |
| **Flexibility** | Must rehash all data | Only affected portion moves |
| **Complexity** | Simple O(1) | Moderate O(log n) |
| **Used By** | Small systems | DynamoDB, Cassandra, Redis |

## Virtual Nodes Explained

Each physical shard has 150 virtual nodes distributed around the hash ring:

```
Physical Shard 0:
  - shard_0_vnode_0 → hash = 12345678
  - shard_0_vnode_1 → hash = 87654321
  - ... (148 more)

Physical Shard 1:
  - shard_1_vnode_0 → hash = 23456789
  - shard_1_vnode_1 → hash = 98765432
  - ... (148 more)
```

**Why 150 virtual nodes?**
- Better statistical distribution
- Reduces variance in load per shard
- Industry standard balance between distribution quality and lookup speed

## Clean Up

```bash
# Stop all services
docker-compose --profile with-shard-2 down

# Remove all data
docker-compose --profile with-shard-2 down -v
```

## Next Steps

- Compare actual migration results with Phase 3 (modulo-based)
- Visualize hash ring distribution in Splunk
- Experiment with different virtual node counts
- Implement actual data migration between shards
