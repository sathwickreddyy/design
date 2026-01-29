# Task Locking Demo with PostgreSQL

## 🎯 Purpose

This project demonstrates **database-level task locking** using PostgreSQL's `SELECT FOR UPDATE SKIP LOCKED` feature. Multiple workers compete for tasks without conflicts, race conditions, or duplicate processing.

## 🏗️ Architecture

```
┌─────────┐
│ Client  │
└────┬────┘
     │
     ▼
┌─────────────┐
│   Nginx     │  Port 8080 (Round Robin)
└──────┬──────┘
       │
       ├──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐
   │Worker-1│ │Worker-2│ │Worker-3│
   └───┬────┘ └───┬────┘ └───┬────┘
       │          │          │
       └──────────┴──────────┴─────────┐
                                       ▼
                              ┌─────────────────┐
                              │   PostgreSQL    │
                              │  (Port 5433)    │
                              └─────────────────┘
```

## 🔐 Key Concept: SELECT FOR UPDATE SKIP LOCKED

```sql
SELECT id, title 
FROM tasks 
WHERE status = 'PENDING' 
ORDER BY id 
LIMIT 1 
FOR UPDATE SKIP LOCKED
```

### How it works:
1. **FOR UPDATE**: Locks the selected row for the current transaction
2. **SKIP LOCKED**: Skips rows already locked by other transactions
3. **Result**: Each worker grabs a different task - no conflicts!

### Without SKIP LOCKED:
- Workers would **wait** for locks to release
- Multiple workers might compete for the same task
- Slower processing due to lock contention

### With SKIP LOCKED:
- Workers **skip** locked tasks and grab available ones
- Each worker gets a unique task
- Maximum throughput with zero conflicts

## 📋 Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for test scripts)

## 🚀 Quick Start

### 1. Start the Services

```bash
cd locking
docker-compose up -d
```

This starts:
- 3 FastAPI worker containers
- 1 PostgreSQL database
- 1 Nginx load balancer

### 2. Verify Services

```bash
# Check containers are running
docker-compose ps

# Check nginx
curl http://localhost:8080/

# Check database
docker-compose logs postgres
```

### 3. Run the Locking Test

```bash
# Install Python dependencies
pip install requests

# Run the test script
python test_task_locking.py
```

Expected output:
```
🔐 TASK LOCKING DEMO - SELECT FOR UPDATE SKIP LOCKED
======================================================================

🗑️  Resetting all tasks...
✅ All tasks deleted

🏗️  Creating 30 test tasks...
✅ Created 30 tasks by WORKER-1-🟢

🚀 Launching 15 concurrent task-grab requests...
======================================================================
✅ Request # 1: Task # 1 grabbed by WORKER-1-🟢          (2.15s)
✅ Request # 2: Task # 2 grabbed by WORKER-2-🔵          (2.18s)
✅ Request # 3: Task # 3 grabbed by WORKER-3-🟣          (2.16s)
...
======================================================================
📊 SUMMARY
======================================================================

Total Requests:    15
Successful:        15
Failed/No Task:    0
Total Time:        2.20s
Avg Time/Request:  0.15s

📈 Tasks Processed Per Worker:
   WORKER-1-🟢          5 tasks  █████
   WORKER-2-🔵          5 tasks  █████
   WORKER-3-🟣          5 tasks  █████

======================================================================

💡 KEY OBSERVATIONS:
   • Each request grabbed a DIFFERENT task (no conflicts)
   • Tasks distributed across all 3 workers (load balancing)
   • SELECT FOR UPDATE SKIP LOCKED prevented race conditions
   • Lock held during 2-second sleep (connection stays open)
======================================================================
```

## 🧪 Manual Testing

### Create Tasks
```bash
curl -X POST "http://localhost:8080/create-tasks?count=20"
```

### View All Tasks
```bash
curl http://localhost:8080/tasks
```

### Grab a Task
```bash
curl -X POST http://localhost:8080/grab-task
```

### Reset Tasks
```bash
curl -X DELETE http://localhost:8080/reset-tasks
```

## 📊 Understanding the Demo

### What Happens When You Run the Test:

1. **15 concurrent requests** are sent to grab tasks
2. **Nginx** distributes requests across 3 workers (round-robin)
3. **Each worker** executes `SELECT FOR UPDATE SKIP LOCKED`
4. **Database** ensures:
   - Only one worker can lock each task
   - Other workers skip locked tasks and grab different ones
5. **Workers process** tasks (simulate 2-second work)
6. **Result**: All 15 tasks completed without conflicts

### Database State During Processing:

```
Task #1: 🔒 LOCKED by WORKER-1 (processing)
Task #2: 🔒 LOCKED by WORKER-2 (processing)
Task #3: 🔒 LOCKED by WORKER-3 (processing)
Task #4: ⏳ PENDING (available for next request)
Task #5: ⏳ PENDING (available for next request)
...
```

## 🛠️ Customization

### Change Number of Workers

Edit `docker-compose.yml`:
```yaml
worker4:
  build: .
  container_name: locking-worker4
  environment:
    - APP_NAME=WORKER-4-🟡
    - DATABASE_URL=postgresql://taskuser:taskpass@postgres:5432/taskdb
```

Don't forget to add it to nginx.conf:
```nginx
upstream worker_servers {
    server worker1:8000;
    server worker2:8000;
    server worker3:8000;
    server worker4:8000;
}
```

### Change Processing Time

Edit `app/main.py`:
```python
time.sleep(5)  # Change from 2 seconds to 5 seconds
```

## 🐛 Troubleshooting

### Port Already in Use
If port 8080 or 5433 is already in use:

```yaml
# In docker-compose.yml
ports:
  - "8081:80"  # Change nginx port
  - "5434:5432"  # Change postgres port
```

### Database Connection Issues
```bash
# Check database logs
docker-compose logs postgres

# Restart services
docker-compose down
docker-compose up -d
```

### View Worker Logs
```bash
# All workers
docker-compose logs -f worker1 worker2 worker3

# Specific worker
docker-compose logs -f worker1
```

## 🧹 Cleanup

```bash
# Stop containers
docker-compose down

# Stop and remove volumes (deletes all data)
docker-compose down -v

# Remove images
docker-compose down --rmi all
```

## 📚 Learning Points

1. **Database-Level Locking**: PostgreSQL provides row-level locking with `FOR UPDATE`
2. **SKIP LOCKED**: Prevents lock contention by skipping locked rows
3. **Load Balancing**: Nginx distributes requests across workers
4. **Concurrency**: Multiple workers process tasks simultaneously without conflicts
5. **Idempotency**: Each task processed exactly once

## 🔍 Real-World Use Cases

- **Job Queues**: Workers processing background jobs
- **Task Distribution**: Distributing work across microservices
- **Rate Limiting**: Preventing duplicate API calls
- **Order Processing**: Multiple servers processing orders
- **Data Pipeline**: Parallel data processing without duplicates

## 📖 Further Reading

- [PostgreSQL SELECT FOR UPDATE](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [Row-Level Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [FastAPI Concurrency](https://fastapi.tiangolo.com/async/)
- [SQLAlchemy Core](https://docs.sqlalchemy.org/en/20/core/)

## 📝 License

MIT
