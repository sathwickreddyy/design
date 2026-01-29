#!/usr/bin/env python3
"""
Database initialization script.
Run this once before starting workers to create tables.
"""
import os
import sys
import time
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import OperationalError
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://taskuser:taskpass@localhost:5433/taskdb")

Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    status = Column(String, default="PENDING", index=True)
    locked_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


def init_database(max_retries=5):
    """Initialize database with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"🔄 Attempt {attempt}/{max_retries}: Connecting to database...")
            engine = create_engine(DATABASE_URL, pool_pre_ping=True)
            
            # Test connection
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            print("✅ Connected to database successfully")
            
            # Create tables
            print("🏗️  Creating tables...")
            Base.metadata.create_all(bind=engine, checkfirst=True)
            print("✅ Tables created successfully")
            
            return True
            
        except OperationalError as e:
            print(f"❌ Attempt {attempt} failed: {e}")
            if attempt < max_retries:
                wait_time = 2 * attempt
                print(f"⏳ Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                print(f"❌ Failed to initialize database after {max_retries} attempts")
                return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
    
    return False


if __name__ == "__main__":
    print("="*70)
    print("  📊 DATABASE INITIALIZATION")
    print("="*70)
    print(f"Database URL: {DATABASE_URL}")
    print()
    
    success = init_database()
    
    if success:
        print()
        print("="*70)
        print("  ✅ DATABASE READY")
        print("="*70)
        sys.exit(0)
    else:
        print()
        print("="*70)
        print("  ❌ DATABASE INITIALIZATION FAILED")
        print("="*70)
        sys.exit(1)
