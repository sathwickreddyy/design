"""
Drive Clone - Sharded Database Ingestion Service

This module implements a simple sharding strategy for distributing file metadata
across multiple PostgreSQL databases using modulo-based routing.

Purpose:
    Demonstrate data distribution across database shards for educational purposes.

Consumers:
    FastAPI endpoints for data ingestion and querying.

Logic:
    1. Connect to multiple PostgreSQL shards
    2. Route data based on user_id % num_shards
    3. Create tables if they don't exist
    4. Insert file metadata and track distribution
"""

import logging
import os
from typing import List, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Drive Clone Sharding API")

# Database configuration from environment variables
SHARD_CONFIGS = [
    {
        "host": os.getenv("DB_SHARD_0_HOST", "db_shard_0"),
        "port": int(os.getenv("DB_SHARD_0_PORT", "5432")),
        "user": os.getenv("DB_SHARD_0_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_0_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_0_NAME", "drive_shard_0"),
        "shard_id": 0
    },
    {
        "host": os.getenv("DB_SHARD_1_HOST", "db_shard_1"),
        "port": int(os.getenv("DB_SHARD_1_PORT", "5432")),
        "user": os.getenv("DB_SHARD_1_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_1_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_1_NAME", "drive_shard_1"),
        "shard_id": 1
    },
    {
        "host": os.getenv("DB_SHARD_2_HOST", "db_shard_2"),
        "port": int(os.getenv("DB_SHARD_2_PORT", "5432")),
        "user": os.getenv("DB_SHARD_2_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_2_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_2_NAME", "drive_shard_2"),
        "shard_id": 2
    }
]

NUM_SHARDS = len(SHARD_CONFIGS)


class FileMetadata(BaseModel):
    """
    Schema for file metadata.
    
    Attributes:
        user_id: Unique identifier for the user
        file_name: Name of the file
    """
    user_id: int
    file_name: str


@contextmanager
def get_db_connection(shard_id: int):
    """
    Create a database connection context manager for a specific shard.
    
    Purpose:
        Provide safe database connections with automatic cleanup.
    
    Consumers:
        All database operations requiring connections.
    
    Logic:
        1. Retrieve shard configuration
        2. Establish connection
        3. Yield connection
        4. Close connection on exit (success or failure)
    
    Args:
        shard_id: Index of the shard to connect to
        
    Yields:
        psycopg2.connection: Database connection
        
    Raises:
        ValueError: If shard_id is invalid
        psycopg2.Error: If connection fails
    """
    if shard_id < 0 or shard_id >= NUM_SHARDS:
        error_msg = f"Invalid shard_id: {shard_id}. Must be between 0 and {NUM_SHARDS - 1}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    config = SHARD_CONFIGS[shard_id]
    logger.debug(f"Connecting to shard {shard_id} at {config['host']}:{config['port']}")
    
    conn = None
    try:
        conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"]
        )
        logger.debug(f"Successfully connected to shard {shard_id}")
        yield conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error for shard {shard_id}: {e}")
        raise
    finally:
        if conn:
            conn.close()
            logger.debug(f"Connection to shard {shard_id} closed")


def get_shard_id(user_id: int) -> int:
    """
    Calculate which shard a user's data should be stored in.
    
    Purpose:
        Implement modulo-based sharding strategy.
    
    Consumers:
        All data ingestion and query operations.
    
    Logic:
        1. Apply modulo operation: user_id % num_shards
        2. Return resulting shard index
    
    Args:
        user_id: User identifier
        
    Returns:
        int: Shard index (0 to NUM_SHARDS - 1)
    """
    shard_id = user_id % NUM_SHARDS
    logger.debug(f"User {user_id} -> Shard {shard_id}")
    return shard_id


def create_tables():
    """
    Create file_metadata table in all shards if it doesn't exist.
    
    Purpose:
        Initialize database schema across all shards.
    
    Consumers:
        Application startup routine.
    
    Logic:
        1. Iterate through all shards
        2. Connect to each shard
        3. Execute CREATE TABLE IF NOT EXISTS
        4. Log success/failure for each shard
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS file_metadata (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX IF NOT EXISTS idx_user_id ON file_metadata(user_id);
    """
    
    logger.info("Creating tables in all shards...")
    
    for shard_id in range(NUM_SHARDS):
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
    """
    Insert file metadata into the appropriate shard.
    
    Purpose:
        Store file metadata in the correct shard based on user_id.
    
    Consumers:
        POST /ingest endpoint.
    
    Logic:
        1. Calculate target shard using modulo routing
        2. Connect to the target shard
        3. Insert record
        4. Return insertion details with shard information
    
    Args:
        user_id: User identifier
        file_name: Name of the file
        
    Returns:
        dict: Insertion result with record_id and shard_id
        
    Raises:
        psycopg2.Error: If insertion fails
    """
    shard_id = get_shard_id(user_id)
    
    logger.info(f"Inserting record for user {user_id} into shard {shard_id}")
    
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
                
                logger.info(f"✓ Inserted record {record_id} for user {user_id} in shard {shard_id}")
                return result
    except Exception as e:
        logger.error(f"✗ Failed to insert record for user {user_id}: {e}")
        raise


def check_mapping() -> Dict[str, Any]:
    """
    Analyze how existing data would be redistributed with current sharding strategy.
    
    Purpose:
        Show the impact of changing sharding strategy from %2 to %3.
        Demonstrates the challenge of resharding existing data.
    
    Consumers:
        GET /migration/analysis endpoint.
    
    Logic:
        1. Read all existing records from all shards
        2. Calculate current shard (where data currently lives)
        3. Calculate new shard using current NUM_SHARDS (user_id % 3)
        4. Compare and track: records that stay vs need migration
        5. Provide detailed breakdown per shard and per user
    
    Returns:
        dict: Migration analysis with statistics and detailed mapping
    """
    logger.info("=== Starting Migration Analysis ===")
    logger.info(f"Current sharding strategy: user_id % {NUM_SHARDS}")
    
    # Track statistics
    total_records = 0
    records_stay = 0
    records_move = 0
    
    # Track migrations per shard
    shard_analysis = {}
    user_movements = []  # Detailed user-by-user tracking
    
    # Analyze old 2-shard configuration (before adding shard 2)
    old_num_shards = 2
    
    # Read all records from existing shards (0 and 1)
    for old_shard_id in range(old_num_shards):
        try:
            with get_db_connection(old_shard_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT id, user_id, file_name FROM file_metadata ORDER BY user_id;")
                    records = cursor.fetchall()
                    
                    shard_analysis[old_shard_id] = {
                        "current_shard": old_shard_id,
                        "total_records": len(records),
                        "stay_count": 0,
                        "move_count": 0,
                        "migrations_to": {}
                    }
                    
                    for record in records:
                        total_records += 1
                        user_id = record['user_id']
                        
                        # Calculate old shard (user_id % 2)
                        old_shard = user_id % old_num_shards
                        
                        # Calculate new shard (user_id % 3)
                        new_shard = get_shard_id(user_id)  # Uses current NUM_SHARDS
                        
                        if old_shard == new_shard:
                            records_stay += 1
                            shard_analysis[old_shard_id]["stay_count"] += 1
                        else:
                            records_move += 1
                            shard_analysis[old_shard_id]["move_count"] += 1
                            
                            # Track destination
                            if new_shard not in shard_analysis[old_shard_id]["migrations_to"]:
                                shard_analysis[old_shard_id]["migrations_to"][new_shard] = 0
                            shard_analysis[old_shard_id]["migrations_to"][new_shard] += 1
                        
                        # Store detailed movement info for logging
                        user_movements.append({
                            "user_id": user_id,
                            "file_name": record['file_name'],
                            "current_shard": old_shard,
                            "new_shard": new_shard,
                            "needs_migration": old_shard != new_shard
                        })
                        
                        # Log every 10th user for visibility
                        if total_records % 10 == 0:
                            status = "STAY" if old_shard == new_shard else f"MOVE {old_shard}→{new_shard}"
                            logger.info(f"User {user_id}: {status}")
        
        except Exception as e:
            logger.error(f"Failed to analyze shard {old_shard_id}: {e}")
            raise
    
    # Calculate percentages
    stay_percentage = (records_stay / total_records * 100) if total_records > 0 else 0
    move_percentage = (records_move / total_records * 100) if total_records > 0 else 0
    
    # Log summary
    logger.info("=== Migration Analysis Summary ===")
    logger.info(f"Total records analyzed: {total_records}")
    logger.info(f"Records that STAY in current shard: {records_stay} ({stay_percentage:.1f}%)")
    logger.info(f"Records that NEED MIGRATION: {records_move} ({move_percentage:.1f}%)")
    
    for shard_id, analysis in shard_analysis.items():
        logger.info(f"\nShard {shard_id}:")
        logger.info(f"  Current records: {analysis['total_records']}")
        logger.info(f"  Will stay: {analysis['stay_count']}")
        logger.info(f"  Will move: {analysis['move_count']}")
        if analysis['migrations_to']:
            for dest_shard, count in analysis['migrations_to'].items():
                logger.info(f"    → To Shard {dest_shard}: {count} records")
    
    return {
        "old_sharding_strategy": f"user_id % {old_num_shards}",
        "new_sharding_strategy": f"user_id % {NUM_SHARDS}",
        "total_records": total_records,
        "records_stay": records_stay,
        "records_move": records_move,
        "stay_percentage": round(stay_percentage, 2),
        "move_percentage": round(move_percentage, 2),
        "shard_analysis": shard_analysis,
        "sample_movements": user_movements[:20]  # First 20 for inspection
    }


def get_shard_stats() -> List[Dict[str, Any]]:
    """
    Get record count statistics from all shards.
    
    Purpose:
        Provide visibility into data distribution across shards.
    
    Consumers:
        GET /stats endpoint.
    
    Logic:
        1. Iterate through all shards
        2. Query record count from each shard
        3. Aggregate and return statistics
    
    Returns:
        list: Statistics for each shard including count
    """
    stats = []
    total_records = 0
    
    logger.info("Fetching shard statistics...")
    
    for shard_id in range(NUM_SHARDS):
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
                    logger.info(f"Shard {shard_id}: {count} records")
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
    
    logger.info(f"Total records across all shards: {total_records}")
    return stats


@app.on_event("startup")
async def startup_event():
    """
    Initialize database tables on application startup.
    
    Purpose:
        Ensure all shards have the required schema before accepting requests.
    
    Consumers:
        FastAPI application lifecycle.
    
    Logic:
        1. Call create_tables() to initialize schema
        2. Log startup completion
    """
    logger.info("=== Starting Drive Clone Sharding API ===")
    logger.info(f"Number of shards: {NUM_SHARDS}")
    
    try:
        create_tables()
        logger.info("=== Startup complete ===")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Drive Clone Sharding API",
        "status": "running",
        "num_shards": NUM_SHARDS
    }


@app.post("/ingest")
async def ingest_file(file_metadata: FileMetadata):
    """
    Ingest file metadata into the appropriate shard.
    
    Purpose:
        Accept file metadata and store it in the correct shard.
    
    Consumers:
        External clients/scripts.
    
    Logic:
        1. Receive file metadata
        2. Route to appropriate shard
        3. Insert record
        4. Return confirmation with shard information
    """
    try:
        result = insert_file_metadata(file_metadata.user_id, file_metadata.file_name)
        return {
            "success": True,
            "message": f"File ingested into shard {result['shard_id']}",
            "data": result
        }
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/bulk")
async def ingest_bulk(count: int = 100):
    """
    Generate and insert bulk test data.
    
    Purpose:
        Generate test data for demonstrating shard distribution.
    
    Consumers:
        Testing and demonstration purposes.
    
    Logic:
        1. Generate 'count' number of records with sequential user_ids
        2. Insert each record into appropriate shard
        3. Track distribution across shards
        4. Return summary statistics
    
    Args:
        count: Number of records to generate (default: 100)
    """
    logger.info(f"Starting bulk ingestion of {count} records...")
    
    results = []
    shard_distribution = {i: 0 for i in range(NUM_SHARDS)}
    
    for i in range(count):
        user_id = i
        file_name = f"file_{i}.txt"
        
        try:
            result = insert_file_metadata(user_id, file_name)
            shard_distribution[result["shard_id"]] += 1
            results.append(result)
            
            # Log every 10 records
            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i + 1}/{count} records inserted")
        except Exception as e:
            logger.error(f"Failed to insert record {i}: {e}")
    
    # Log distribution summary
    logger.info("=== Distribution Summary ===")
    for shard_id, count_in_shard in shard_distribution.items():
        percentage = (count_in_shard / count) * 100
        logger.info(f"Shard {shard_id}: {count_in_shard} records ({percentage:.1f}%)")
    
    return {
        "success": True,
        "message": f"Inserted {count} records",
        "distribution": shard_distribution,
        "records": results
    }


@app.get("/stats")
async def get_stats():
    """
    Get distribution statistics across all shards.
    
    Purpose:
        Provide visibility into data distribution.
    
    Consumers:
        Monitoring and visualization tools.
    
    Logic:
        1. Query record counts from all shards
        2. Calculate distribution percentages
        3. Return aggregated statistics
    """
    try:
        stats = get_shard_stats()
        return {
            "success": True,
            "shards": stats,
            "total_shards": NUM_SHARDS
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/migration/analysis")
async def analyze_migration():
    """
    Analyze the impact of changing sharding strategy.
    
    Purpose:
        Show how many records would need to migrate when changing from %2 to %3.
    
    Consumers:
        Administrators planning database resharding.
    
    Logic:
        1. Call check_mapping() to analyze current data
        2. Return detailed migration statistics
        3. Show which users stay and which need to move
    """
    try:
        analysis = check_mapping()
        return {
            "success": True,
            "analysis": analysis
        }
    except Exception as e:
        logger.error(f"Migration analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/query/{user_id}")
async def query_user_files(user_id: int):
    """
    Query all files for a specific user.
    
    Purpose:
        Retrieve all file metadata for a given user from the correct shard.
    
    Consumers:
        Client applications querying user data.
    
    Logic:
        1. Calculate target shard for user_id
        2. Connect to the specific shard
        3. Query all records for the user
        4. Return results with shard information
    
    Args:
        user_id: User identifier to query
    """
    shard_id = get_shard_id(user_id)
    logger.info(f"Querying files for user {user_id} from shard {shard_id}")
    
    query_sql = "SELECT * FROM file_metadata WHERE user_id = %s ORDER BY created_at DESC;"
    
    try:
        with get_db_connection(shard_id) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query_sql, (user_id,))
                files = cursor.fetchall()
                
                # Convert to list of dicts
                result = [dict(row) for row in files]
                
                logger.info(f"Found {len(result)} files for user {user_id} in shard {shard_id}")
                
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
