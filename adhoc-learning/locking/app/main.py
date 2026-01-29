"""
FastAPI application demonstrating database-level task locking.
Uses SELECT FOR UPDATE SKIP LOCKED for concurrent task processing.
"""
import os
import time
from datetime import datetime
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError

app = FastAPI(title="Task Locking Demo")

# Get APP_NAME from environment variable
APP_NAME = os.environ.get("APP_NAME", "unknown")
PROCESS_ID = os.getpid()
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://taskuser:taskpass@localhost:5432/taskdb")

# SQLAlchemy setup
Base = declarative_base()
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ============================================
# DATABASE MODEL
# ============================================
class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    status = Column(String, default="PENDING", index=True)  # PENDING, PROCESSING, COMPLETED
    locked_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


# Initialize database connection
# Note: Tables are created by init_db.py container before workers start
try:
    # Test connection only
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"✅ {APP_NAME} connected to database successfully")
except OperationalError as e:
    print(f"❌ {APP_NAME} failed to connect to database: {e}")
except Exception as e:
    print(f"⚠️  {APP_NAME} database connection warning: {e}")


@contextmanager
def get_db():
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.get("/")
async def root():
    """Root endpoint returning server identification."""
    return {
        "app_name": APP_NAME,
        "process_id": PROCESS_ID,
        "message": f"Hello from {APP_NAME}!",
        "purpose": "Task Locking Demo with SELECT FOR UPDATE SKIP LOCKED"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "app_name": APP_NAME}


# ============================================
# TASK MANAGEMENT ENDPOINTS
# ============================================

@app.post("/create-tasks")
async def create_tasks(count: int = 10):
    """Create test tasks in PENDING state."""
    with get_db() as db:
        tasks_created = []
        for i in range(count):
            task = Task(
                title=f"Task #{i+1}",
                status="PENDING"
            )
            db.add(task)
            tasks_created.append(task.title)
        db.commit()
        
    return {
        "message": f"Created {count} tasks",
        "tasks": tasks_created,
        "server": APP_NAME
    }


@app.get("/tasks")
async def list_tasks():
    """List all tasks with their status."""
    with get_db() as db:
        tasks = db.query(Task).order_by(Task.id).all()
        
        # Count by status
        status_counts = {
            "PENDING": len([t for t in tasks if t.status == "PENDING"]),
            "PROCESSING": len([t for t in tasks if t.status == "PROCESSING"]),
            "COMPLETED": len([t for t in tasks if t.status == "COMPLETED"])
        }
        
        task_list = [{
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "locked_by": t.locked_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        } for t in tasks]
        
    return {
        "total": len(tasks),
        "status_counts": status_counts,
        "tasks": task_list,
        "server": APP_NAME
    }


@app.post("/grab-task")
async def grab_task():
    """
    ╔═══════════════════════════════════════════════════════════════════╗
    ║  GRAB TASK WITH DATABASE-LEVEL LOCKING                             ║
    ║                                                                    ║
    ║  Uses: SELECT ... FOR UPDATE SKIP LOCKED                           ║
    ║                                                                    ║
    ║  How it works:                                                     ║
    ║  1. FOR UPDATE locks the selected row                              ║
    ║  2. SKIP LOCKED skips rows already locked by other transactions    ║
    ║  3. Each server grabs a different task (no conflicts!)             ║
    ║  4. Lock held during sleep (2 seconds) to simulate work            ║
    ║  5. Released on commit                                             ║
    ║                                                                    ║
    ║  WITHOUT SKIP LOCKED: Servers would wait and fight for same task   ║
    ║  WITH SKIP LOCKED: Servers grab different tasks simultaneously     ║
    ╚═══════════════════════════════════════════════════════════════════╝
    """
    db = SessionLocal()
    
    try:
        # Step 1: Find and LOCK a pending task using raw SQL for better control
        # This is the MAGIC: FOR UPDATE SKIP LOCKED prevents contention
        result = db.execute(
            text("""
                SELECT id, title 
                FROM tasks 
                WHERE status = 'PENDING' 
                ORDER BY id 
                LIMIT 1 
                FOR UPDATE SKIP LOCKED
            """)
        ).fetchone()
        
        if not result:
            return {
                "message": "No pending tasks available",
                "server": APP_NAME
            }
        
        task_id, task_title = result
        
        # Step 2: Mark as PROCESSING and lock to this server
        now = datetime.utcnow()
        db.execute(
            text("""
                UPDATE tasks 
                SET status = 'PROCESSING', 
                    locked_by = :server_name,
                    started_at = :started_at
                WHERE id = :task_id
            """),
            {
                "server_name": APP_NAME,
                "task_id": task_id,
                "started_at": now
            }
        )
        db.commit()
        
        # Step 3: Simulate work (CRITICAL: Connection stays open, holding the lock)
        print(f"🔨 {APP_NAME} processing task #{task_id}: {task_title}")
        time.sleep(2)  # Simulate 2 seconds of work
        
        # Step 4: Mark as COMPLETED
        completed_at = datetime.utcnow()
        db.execute(
            text("""
                UPDATE tasks 
                SET status = 'COMPLETED',
                    completed_at = :completed_at
                WHERE id = :task_id
            """),
            {
                "task_id": task_id,
                "completed_at": completed_at
            }
        )
        db.commit()
        
        processing_time = (completed_at - now).total_seconds()
        
        return {
            "message": "Task completed successfully",
            "task": {
                "id": task_id,
                "title": task_title,
                "processed_by": APP_NAME,
                "processing_time_seconds": round(processing_time, 2)
            },
            "server": APP_NAME,
            "process_id": PROCESS_ID
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing task: {str(e)}")
    finally:
        db.close()


@app.delete("/reset-tasks")
async def reset_tasks():
    """Reset all tasks to PENDING (for testing)."""
    with get_db() as db:
        db.execute(text("DELETE FROM tasks"))
        db.commit()
    
    return {
        "message": "All tasks deleted",
        "server": APP_NAME
    }
