# Drive Clone - Database Sharding Simulation

A demonstration of database sharding for a drive clone application using modulo-based routing across multiple PostgreSQL instances.

## Architecture

```
┌─────────────┐
│   FastAPI   │
│   Service   │
└──────┬──────┘
       │
       ├─────────────┬─────────────┐
       │             │             │
       ▼             ▼             ▼
┌───────────┐ ┌───────────┐     ...
│  Shard 0  │ │  Shard 1  │
│ (user_id  │ │ (user_id  │
│  % 2 = 0) │ │  % 2 = 1) │
└───────────┘ └───────────┘
```

## Sharding Strategy

- **Routing Logic:** `shard_id = user_id % num_shards`
- **Number of Shards:** 2 (db_shard_0, db_shard_1)
- **Data Distribution:** Even/Odd user_ids split across shards

## Quick Start

### 1. Create Docker Network (if not exists)
```bash
docker network create observability-net
```

### 2. Start Services
```bash
cd sharding
docker-compose up --build
```

### 3. Test the API

**Insert 100 test records:**
```bash
curl -X POST "http://localhost:8000/ingest/bulk?count=100"
```

**Check distribution stats:**
```bash
curl http://localhost:8000/stats
```

**Query files for specific user:**
```bash
curl http://localhost:8000/query/42
```

**Insert single record:**
```bash
curl -X POST "http://localhost:8000/ingest" \
  -H "Content-Type: application/json" \
  -d '{"user_id": 123, "file_name": "my_document.txt"}'
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

## Connecting via DB UI Tools

### DBeaver / pgAdmin / TablePlus

**Connection for Shard 0:**
```
Host: localhost
Port: 5432
Database: drive_shard_0
Username: shard_user
Password: shard_pass
```

**Connection for Shard 1:**
```
Host: localhost
Port: 5433
Database: drive_shard_1
Username: shard_user
Password: shard_pass
```

### Using psql (Command Line)

**Connect to Shard 0:**
```bash
psql -h localhost -p 5432 -U shard_user -d drive_shard_0
# Password: shard_pass
```

**Connect to Shard 1:**
```bash
psql -h localhost -p 5433 -U shard_user -d drive_shard_1
# Password: shard_pass
```

### Useful SQL Queries

**Check record count:**
```sql
SELECT COUNT(*) FROM file_metadata;
```

**View distribution by user_id:**
```sql
SELECT user_id, COUNT(*) as file_count 
FROM file_metadata 
GROUP BY user_id 
ORDER BY user_id;
```

**View all records:**
```sql
SELECT * FROM file_metadata ORDER BY created_at DESC LIMIT 10;
```

**Check which user_ids are in this shard:**
```sql
SELECT DISTINCT user_id FROM file_metadata ORDER BY user_id;
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/ingest` | POST | Insert single file record |
| `/ingest/bulk?count=N` | POST | Insert N test records |
| `/stats` | GET | Get distribution statistics |
| `/query/{user_id}` | GET | Get all files for a user |

## Expected Results (Phase 1)

When inserting 100 records with sequential user_ids (0-99):

- **Shard 0:** 50 records (even user_ids: 0, 2, 4, ... 98)
- **Shard 1:** 50 records (odd user_ids: 1, 3, 5, ... 99)
- **Distribution:** Exactly 50/50 split

## Monitoring Data Distribution

1. **Via API:**
   ```bash
   curl http://localhost:8000/stats
   ```

2. **Via Database:**
   ```bash
   # Check Shard 0
   psql -h localhost -p 5432 -U shard_user -d drive_shard_0 -c "SELECT COUNT(*) FROM file_metadata;"
   
   # Check Shard 1
   psql -h localhost -p 5433 -U shard_user -d drive_shard_1 -c "SELECT COUNT(*) FROM file_metadata;"
   ```

3. **Via Logs:**
   ```bash
   docker-compose logs -f api
   ```

## Clean Up

**Stop services:**
```bash
docker-compose down
```

**Remove data (fresh start):**
```bash
docker-compose down -v
```

## Next Steps (Future Phases)

- Phase 2: Add more shards and observe redistribution challenges
- Phase 3: Implement consistent hashing
- Phase 4: Add replication and failover
