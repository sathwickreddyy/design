"""
Drive Clone - Consistent Hashing Sharding Service

This service demonstrates consistent hashing for database sharding.
Compared to modulo-based sharding (Phase 1-3), consistent hashing
minimizes data movement when adding/removing shards.

Purpose:
    Route user data to shards using consistent hashing with minimal
    data movement on topology changes.

Consumers:
    API clients for file metadata storage and retrieval.
"""

import logging
import os
import json
from typing import List, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from consistent_hash import ConsistentHashRing

# Configure logging with JSON format for Splunk
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Drive Clone Consistent Hashing API")

# Database configuration
SHARD_CONFIGS = [
    {
        "host": os.getenv("DB_SHARD_0_HOST", "db_shard_0_consistent"),
        "port": int(os.getenv("DB_SHARD_0_PORT", "5432")),
        "user": os.getenv("DB_SHARD_0_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_0_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_0_NAME", "drive_shard_0"),
        "shard_id": 0
    },
    {
        "host": os.getenv("DB_SHARD_1_HOST", "db_shard_1_consistent"),
        "port": int(os.getenv("DB_SHARD_1_PORT", "5432")),
        "user": os.getenv("DB_SHARD_1_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_1_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_1_NAME", "drive_shard_1"),
        "shard_id": 1
    },
    {
        "host": os.getenv("DB_SHARD_2_HOST", "db_shard_2_consistent"),
        "port": int(os.getenv("DB_SHARD_2_PORT", "5432")),
        "user": os.getenv("DB_SHARD_2_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_2_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_2_NAME", "drive_shard_2"),
        "shard_id": 2
    }
]

VIRTUAL_NODES = int(os.getenv("VIRTUAL_NODES_PER_SHARD", "150"))

# Initialize consistent hash ring (start with 2 shards)
hash_ring = ConsistentHashRing(virtual_nodes_per_shard=VIRTUAL_NODES)


class FileMetadata(BaseModel):
    """Schema for file metadata."""
    user_id: int
    file_name: str


@contextmanager
def get_db_connection(shard_id: int):
    """Create database connection context manager."""
    if shard_id < 0 or shard_id >= len(SHARD_CONFIGS):
        raise ValueError(f"Invalid shard_id: {shard_id}")
    
    config = SHARD_CONFIGS[shard_id]
    conn = None
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"]
        )
        yield conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error for shard {shard_id}: {e}")
        raise
    finally:
        if conn:
            conn.close()


def create_tables():
    """Create file_metadata table in all active shards."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS file_metadata (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_user_id ON file_metadata(user_id);
    """
    
    logger.info("Creating tables in all active shards...")
    
    for shard_id in hash_ring.shards:
        try:
            with get_db_connection(shard_id) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(create_table_sql)
                    conn.commit()
                    logger.info(f"✓ Table created/verified in shard {shard_id}")
        except Exception as e:
            logger.error(f"✗ Failed to create table in shard {shard_id}: {e}")
            raise


def insert_file_metadata(user_id: int, file_name: str) -> Dict[str, Any]:
    """Insert file metadata into the appropriate shard using consistent hashing."""
    shard_id = hash_ring.get_shard(user_id)
    
    logger.info(f"Routing user {user_id} to shard {shard_id} via consistent hashing")
    
    insert_sql = """
    INSERT INTO file_metadata (user_id, file_name)
    VALUES (%s, %s)
    RETURNING id;
    """
    
    try:
        with get_db_connection(shard_id) as conn:
            with conn.cursor() as cursor:
                cursor.execute(insert_sql, (user_id, file_name))
                record_id = cursor.fetchone()[0]
                conn.commit()
                
                result = {
                    "record_id": record_id,
                    "user_id": user_id,
                    "file_name": file_name,
                    "shard_id": shard_id
                }
                
                # Log for Splunk
                log_data = {
                    "event": "record_inserted",
                    "user_id": user_id,
                    "shard_id": shard_id,
                    "record_id": record_id
                }
                logger.info(f"SPLUNK: {json.dumps(log_data)}")
                
                return result
    except Exception as e:
        logger.error(f"✗ Failed to insert record for user {user_id}: {e}")
        raise


def get_shard_stats() -> List[Dict[str, Any]]:
    """Get record count statistics from all shards."""
    stats = []
    total_records = 0
    
    logger.info("Fetching shard statistics...")
    
    for shard_id in hash_ring.shards:
        try:
            with get_db_connection(shard_id) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM file_metadata;")
                    count = cursor.fetchone()[0]
                    
                    stats.append({
                        "shard_id": shard_id,
                        "record_count": count,
                        "database": SHARD_CONFIGS[shard_id]["database"]
                    })
                    
                    total_records += count
        except Exception as e:
            logger.error(f"Failed to get stats for shard {shard_id}: {e}")
            stats.append({
                "shard_id": shard_id,
                "record_count": 0,
                "error": str(e)
            })
    
    # Add distribution percentages
    for stat in stats:
        if "error" not in stat and total_records > 0:
            stat["percentage"] = round((stat["record_count"] / total_records) * 100, 2)
    
    return stats


@app.on_event("startup")
async def startup_event():
    """Initialize hash ring and database tables on startup."""
    logger.info("=== Starting Drive Clone Consistent Hashing API ===")
    logger.info(f"Virtual nodes per shard: {VIRTUAL_NODES}")
    
    # Start with 2 shards (Phase 4 test setup)
    logger.info("Initializing with 2 shards...")
    hash_ring.add_shard(0)
    hash_ring.add_shard(1)
    
    try:
        create_tables()
        
        # Log initial ring state
        ring_state = hash_ring.get_ring_state()
        logger.info(f"Initial ring state: {json.dumps(ring_state)}")
        
        logger.info("=== Startup complete ===")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Drive Clone Consistent Hashing API",
        "status": "running",
        "active_shards": list(hash_ring.shards),
        "virtual_nodes_per_shard": VIRTUAL_NODES
    }


@app.post("/ingest")
async def ingest_file(file_metadata: FileMetadata):
    """Ingest file metadata using consistent hashing."""
    try:
        result = insert_file_metadata(file_metadata.user_id, file_metadata.file_name)
        return {
            "success": True,
            "message": f"File routed to shard {result['shard_id']} via consistent hashing",
            "data": result
        }
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/bulk")
async def ingest_bulk(count: int = 1000):
    """Generate and insert bulk test data."""
    logger.info(f"Starting bulk ingestion of {count} records...")
    
    results = []
    shard_distribution = {shard_id: 0 for shard_id in hash_ring.shards}
    
    for i in range(count):
        user_id = i
        file_name = f"file_{i}.txt"
        
        try:
            result = insert_file_metadata(user_id, file_name)
            shard_distribution[result["shard_id"]] += 1
            results.append(result)
            
            # Log progress every 100 records
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{count} records inserted")
        except Exception as e:
            logger.error(f"Failed to insert record {i}: {e}")
    
    # Log distribution summary
    logger.info("=== Distribution Summary ===")
    for shard_id, count_in_shard in shard_distribution.items():
        percentage = (count_in_shard / count) * 100
        logger.info(f"Shard {shard_id}: {count_in_shard} records ({percentage:.1f}%)")
    
    # Log for Splunk
    log_data = {
        "event": "bulk_ingest_complete",
        "total_records": count,
        "distribution": shard_distribution
    }
    logger.info(f"SPLUNK: {json.dumps(log_data)}")
    
    return {
        "success": True,
        "message": f"Inserted {count} records",
        "distribution": shard_distribution
    }


@app.get("/stats")
async def get_stats():
    """Get distribution statistics across all shards."""
    try:
        stats = get_shard_stats()
        ring_state = hash_ring.get_ring_state()
        
        return {
            "success": True,
            "shards": stats,
            "ring_state": ring_state
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ring/add_shard/{shard_id}")
async def add_shard(shard_id: int):
    """Add a new shard to the consistent hash ring."""
    try:
        if shard_id in hash_ring.shards:
            return {"success": False, "message": f"Shard {shard_id} already exists"}
        
        logger.info(f"Adding shard {shard_id} to hash ring...")
        hash_ring.add_shard(shard_id)
        
        # Create table in new shard
        create_tables()
        
        ring_state = hash_ring.get_ring_state()
        
        return {
            "success": True,
            "message": f"Shard {shard_id} added to ring",
            "ring_state": ring_state
        }
    except Exception as e:
        logger.error(f"Failed to add shard {shard_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ring/state")
async def get_ring_state():
    """Get current hash ring state."""
    try:
        state = hash_ring.get_ring_state()
        return {
            "success": True,
            "ring_state": state
        }
    except Exception as e:
        logger.error(f"Failed to get ring state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ring/analyze_add/{shard_id}")
async def analyze_add_shard(shard_id: int):
    """Analyze the impact of adding a new shard WITHOUT actually adding it."""
    try:
        analysis = hash_ring.analyze_redistribution(shard_id)
        return {
            "success": True,
            "analysis": analysis
        }
    except Exception as e:
        logger.error(f"Failed to analyze adding shard {shard_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/{user_id}")
async def query_user_files(user_id: int):
    """Query all files for a specific user."""
    shard_id = hash_ring.get_shard(user_id)
    logger.info(f"Querying files for user {user_id} from shard {shard_id}")
    
    query_sql = "SELECT * FROM file_metadata WHERE user_id = %s ORDER BY created_at DESC;"
    
    try:
        with get_db_connection(shard_id) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query_sql, (user_id,))
                files = cursor.fetchall()
                result = [dict(row) for row in files]
                
                return {
                    "success": True,
                    "user_id": user_id,
                    "shard_id": shard_id,
                    "file_count": len(result),
                    "files": result
                }
    except Exception as e:
        logger.error(f"Query failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/migration/compare_approaches")
async def compare_migration_approaches():
    """
    Compare Naive (Modulo) vs Consistent Hashing migration impact.
    
    Shows detailed table of each user:
    - Where they are NOW (with 2 shards)
    - Where they WILL BE (with 3 shards)
    - WHY they move (virtual node analysis)
    - Comparison with modulo approach
    """
    import time
    start_time = time.time()
    
    # Get all existing users from shards 0 and 1
    all_users = []
    for shard_id in [0, 1]:
        try:
            with get_db_connection(shard_id) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT DISTINCT user_id FROM file_metadata ORDER BY user_id")
                    users = cursor.fetchall()
                    all_users.extend([user[0] for user in users])
        except Exception as e:
            logger.error(f"Failed to get users from shard {shard_id}: {e}")
    
    if not all_users:
        return {"success": False, "message": "No users found"}
    
    all_users = sorted(set(all_users))
    
    # Create a ring WITH shard 2 for comparison
    ring_with_3_shards = ConsistentHashRing(virtual_nodes_per_shard=VIRTUAL_NODES)
    ring_with_3_shards.add_shard(0)
    ring_with_3_shards.add_shard(1)
    ring_with_3_shards.add_shard(2)
    
    # Analyze each user
    migration_details = []
    consistent_moves = 0
    modulo_moves = 0
    
    for user_id in all_users:
        # Current routing (2 shards)
        old_shard_consistent = hash_ring.get_shard(user_id)
        old_shard_modulo = user_id % 2
        
        # New routing (3 shards)
        new_shard_consistent = ring_with_3_shards.get_shard(user_id)
        new_shard_modulo = user_id % 3
        
        # Get hash and virtual node details
        user_hash = hash_ring._hash(str(user_id))
        
        # Find which virtual node serves this user (OLD ring)
        ring_positions = [pos for pos, _ in hash_ring.ring]
        import bisect
        old_index = bisect.bisect_right(ring_positions, user_hash)
        if old_index == len(hash_ring.ring):
            old_index = 0
        old_vnode_pos, old_vnode_shard = hash_ring.ring[old_index]
        
        # Find which virtual node serves this user (NEW ring)
        new_ring_positions = [pos for pos, _ in ring_with_3_shards.ring]
        new_index = bisect.bisect_right(new_ring_positions, user_hash)
        if new_index == len(ring_with_3_shards.ring):
            new_index = 0
        new_vnode_pos, new_vnode_shard = ring_with_3_shards.ring[new_index]
        
        # Check movements
        consistent_moved = old_shard_consistent != new_shard_consistent
        modulo_moved = old_shard_modulo != new_shard_modulo
        
        if consistent_moved:
            consistent_moves += 1
        if modulo_moved:
            modulo_moves += 1
        
        # Determine reason for movement
        reason = "No movement - same virtual node serves user"
        if consistent_moved:
            reason = f"NEW virtual node (shard_{new_vnode_shard}) inserted between user_hash={user_hash} and old_vnode={old_vnode_pos}"
        
        migration_details.append({
            "user_id": user_id,
            "user_hash": user_hash,
            "consistent_hashing": {
                "old_shard": old_shard_consistent,
                "new_shard": new_shard_consistent,
                "old_vnode_position": old_vnode_pos,
                "new_vnode_position": new_vnode_pos,
                "moved": consistent_moved,
                "reason": reason
            },
            "modulo_hashing": {
                "old_shard": old_shard_modulo,
                "new_shard": new_shard_modulo,
                "moved": modulo_moved,
                "reason": f"user_id % 3 = {new_shard_modulo}" if modulo_moved else "No change"
            }
        })
    
    elapsed_time = time.time() - start_time
    
    # Summary statistics
    total_users = len(all_users)
    consistent_pct = (consistent_moves / total_users) * 100
    modulo_pct = (modulo_moves / total_users) * 100
    
    result = {
        "success": True,
        "analysis_time_seconds": round(elapsed_time, 3),
        "total_users_analyzed": total_users,
        "summary": {
            "consistent_hashing": {
                "users_that_move": consistent_moves,
                "users_that_stay": total_users - consistent_moves,
                "movement_percentage": round(consistent_pct, 2),
                "theoretical_movement": 33.33
            },
            "modulo_hashing": {
                "users_that_move": modulo_moves,
                "users_that_stay": total_users - modulo_moves,
                "movement_percentage": round(modulo_pct, 2),
                "theoretical_movement": 66.67
            },
            "savings": {
                "fewer_moves": modulo_moves - consistent_moves,
                "percentage_improvement": round(modulo_pct - consistent_pct, 2)
            }
        },
        "detailed_migrations": migration_details[:50],  # First 50 for readability
        "full_report_available": len(migration_details)
    }
    
    logger.info(f"SPLUNK: {json.dumps({'event': 'migration_comparison', 'summary': result['summary']})}")
    
    return result
