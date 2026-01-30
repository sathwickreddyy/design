#!/usr/bin/env python3
"""
Database Resharding Migration Script - The Nightmare Scenario

This script demonstrates the REAL-WORLD CHALLENGES of resharding a production database.
While this works fine for 100 records, imagine running this on 1TB of data with millions
of active users.

WHY THIS IS A NIGHTMARE AT SCALE:
================================

1. TIME COMPLEXITY - The 1TB Problem:
   - Reading 1TB of data from source shards: Hours to days
   - Writing 66% of that data to new shards: Hours to days
   - Deleting from old shards: Hours
   - Network transfer time: Depends on bandwidth, could be days
   - With our 66% migration rate, we're moving ~660GB of data
   - At 100MB/s: ~1.8 hours just for data transfer
   - At 10MB/s (realistic with network overhead): ~18 hours
   - Database I/O becomes the bottleneck

2. DOWNTIME REQUIREMENTS:
   - You MUST take the application offline during migration
   - Any writes during migration create inconsistency
   - 18-24 hour downtime? Your business loses millions
   - Your customers? They're furious

3. THE USER 5 SCENARIO - Race Condition Nightmare:
   ===================================================
   Let's trace what happens if User 5 uploads a file DURING migration:
   
   Timeline:
   ---------
   T0: Migration starts
       - User 5's old data is in Shard 1 (user_id % 2 = 1)
       - Script begins reading data from Shard 1
   
   T1: Migration is processing User 3's data
       - User 5's old files still in Shard 1
       - User 5 uploads "important_report.pdf"
       - NEW routing logic: user_id % 3 = 2 → Goes to Shard 2 ✓
       - OLD data still in Shard 1
       - User 5 now has data in BOTH Shard 1 AND Shard 2!
   
   T2: Migration reaches User 5
       - Reads User 5's OLD files from Shard 1: ["old_file1.txt", "old_file2.txt"]
       - Inserts them into Shard 2 (correct new location)
       - Shard 2 now has: ["old_file1.txt", "old_file2.txt", "important_report.pdf"] ✓
       - Deletes User 5's data from Shard 1
   
   T3: User 5 tries to list their files
       - Application queries Shard 2 (user_id % 3 = 2)
       - Sees all files ✓
   
   BUT WHAT IF THE TIMING IS SLIGHTLY DIFFERENT?
   
   SCENARIO A - Data Loss:
   -----------------------
   T1: Migration reads User 5's data from Shard 1
   T2: User 5 uploads "important_report.pdf" → Goes to Shard 2
   T3: Migration writes OLD data to Shard 2 (might overwrite?)
   T4: Migration deletes from Shard 1
   T5: "important_report.pdf" might be LOST if we're not careful!
   
   SCENARIO B - Duplicate Writes:
   ------------------------------
   T1: User 5 uploads "doc.pdf" → Shard 2 (new routing)
   T2: Migration copies "doc.pdf" from Shard 1 to Shard 2
   T3: Now you have TWO entries for "doc.pdf" with different IDs!
   T4: Which one is correct? No idea!
   
   SCENARIO C - Partial State:
   ---------------------------
   T1: User 5 has 100 files in Shard 1
   T2: Migration starts moving them to Shard 2
   T3: Network failure after moving 50 files
   T4: User 5 has 50 files in Shard 1, 50 in Shard 2
   T5: Application only queries Shard 2
   T6: User 5 sees only HALF their files!
   
   THE SOLUTION? 
   - Take the app OFFLINE during migration (downtime)
   - Use row-level locking (performance nightmare)
   - Use distributed transactions (complex, slow, can deadlock)
   - Use a dual-write period with shadow mode (complex to implement)

4. NETWORK OVERHEAD:
   - 660GB moving across network interfaces
   - Each record: SELECT from source, INSERT to destination, DELETE from source
   - That's 3x the network traffic
   - Database connections might timeout
   - You need connection pooling, retry logic, checkpoint/resume capability

5. MEMORY CONSTRAINTS:
   - Can't load all data into memory at once
   - Need batch processing
   - Batch size too small? Migration takes forever
   - Batch size too large? Out of memory errors

6. CONSISTENCY CHALLENGES:
   - What if migration fails halfway?
   - Need rollback strategy
   - Need to track which records were migrated
   - Need idempotency (safe to re-run)

7. THE MODULO PROBLEM - Why 66% Had to Move:
   =========================================
   Original: user_id % 2 (2 shards)
   - Even users (0,2,4,6...) → Shard 0
   - Odd users (1,3,5,7...) → Shard 1
   
   New: user_id % 3 (3 shards)
   - user_id % 3 = 0 (0,3,6,9...) → Shard 0
   - user_id % 3 = 1 (1,4,7,10...) → Shard 1
   - user_id % 3 = 2 (2,5,8,11...) → Shard 2
   
   Who stays in Shard 0?
   - Only users where (user_id % 2 = 0) AND (user_id % 3 = 0)
   - That's users divisible by both 2 and 3: 0,6,12,18,24,30,36...
   - Out of 50 users, only 17 stay!
   
   Who stays in Shard 1?
   - Only users where (user_id % 2 = 1) AND (user_id % 3 = 1)
   - That's users where user_id ≡ 1 (mod 2) AND user_id ≡ 1 (mod 3)
   - Users: 1,7,13,19,25,31,37... (again ~17)
   
   RESULT: Only 34 out of 100 stay put. 66 MUST MOVE!
   
   This is why companies use Consistent Hashing instead of modulo.

8. PRODUCTION REALITIES:
   - You need monitoring during migration
   - You need alerting if something fails
   - You need to communicate downtime to users
   - You might need to migrate in phases (even more complex)
   - You need a tested rollback plan
   - You need to verify data integrity after migration

BETTER SOLUTIONS:
================
1. Consistent Hashing - Minimizes data movement when adding shards
2. Virtual Shards - Add new physical shards without changing routing
3. Range-based Sharding - More predictable, but can create hotspots
4. Directory-based Sharding - Lookup table for user → shard mapping
"""

import os
import sys
import logging
import time
from typing import Dict, List, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
SHARD_CONFIGS = [
    {
        "host": os.getenv("DB_SHARD_0_HOST", "localhost"),
        "port": int(os.getenv("DB_SHARD_0_PORT", "5432")),
        "user": os.getenv("DB_SHARD_0_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_0_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_0_NAME", "drive_shard_0"),
        "shard_id": 0
    },
    {
        "host": os.getenv("DB_SHARD_1_HOST", "localhost"),
        "port": int(os.getenv("DB_SHARD_1_PORT", "5433")),
        "user": os.getenv("DB_SHARD_1_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_1_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_1_NAME", "drive_shard_1"),
        "shard_id": 1
    },
    {
        "host": os.getenv("DB_SHARD_2_HOST", "localhost"),
        "port": int(os.getenv("DB_SHARD_2_PORT", "5434")),
        "user": os.getenv("DB_SHARD_2_USER", "shard_user"),
        "password": os.getenv("DB_SHARD_2_PASSWORD", "shard_pass"),
        "database": os.getenv("DB_SHARD_2_NAME", "drive_shard_2"),
        "shard_id": 2
    }
]

OLD_NUM_SHARDS = 2  # Original sharding strategy
NEW_NUM_SHARDS = 3  # New sharding strategy


@contextmanager
def get_db_connection(shard_id: int):
    """
    Create a database connection to a specific shard.
    
    Purpose:
        Provide safe database connections with automatic cleanup.
    
    Args:
        shard_id: Index of the shard to connect to
        
    Yields:
        psycopg2.connection: Database connection
    """
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


def get_new_shard_id(user_id: int) -> int:
    """
    Calculate the new shard for a user based on new sharding strategy.
    
    Purpose:
        Determine where data should be after migration.
    
    Logic:
        Apply new modulo operation: user_id % NEW_NUM_SHARDS
    
    Args:
        user_id: User identifier
        
    Returns:
        int: New shard index
    """
    return user_id % NEW_NUM_SHARDS


def get_old_shard_id(user_id: int) -> int:
    """
    Calculate the old shard for a user based on old sharding strategy.
    
    Purpose:
        Determine where data currently lives before migration.
    
    Logic:
        Apply old modulo operation: user_id % OLD_NUM_SHARDS
    
    Args:
        user_id: User identifier
        
    Returns:
        int: Old shard index
    """
    return user_id % OLD_NUM_SHARDS


def migrate_record(record: Dict[str, Any], from_shard: int, to_shard: int) -> bool:
    """
    Migrate a single record from one shard to another.
    
    Purpose:
        Move one record from source shard to destination shard.
    
    Consumers:
        Main migration loop.
    
    Logic:
        1. Begin transaction on destination shard
        2. INSERT record into new shard
        3. DELETE record from old shard
        4. Commit both operations
        
    DANGER ZONE - Race Conditions:
    =============================
    During this operation, the record exists in BOTH shards temporarily!
    If the application is still running:
    - Queries might hit the old shard (stale data)
    - New writes go to the new shard (new data)
    - Data inconsistency guaranteed!
    
    With 1TB of data:
    - This operation might take milliseconds to seconds PER RECORD
    - Multiply by millions of records
    - Days of inconsistency window
    
    Args:
        record: Record data to migrate
        from_shard: Source shard ID
        to_shard: Destination shard ID
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Insert into new shard
        with get_db_connection(to_shard) as dest_conn:
            with dest_conn.cursor() as cursor:
                insert_sql = """
                    INSERT INTO file_metadata (user_id, file_name, created_at)
                    VALUES (%s, %s, %s)
                """
                cursor.execute(insert_sql, (
                    record['user_id'],
                    record['file_name'],
                    record.get('created_at')
                ))
                dest_conn.commit()
        
        # Delete from old shard
        # DANGER: There's a time gap between INSERT and DELETE
        # If power fails here, you have duplicates!
        with get_db_connection(from_shard) as source_conn:
            with source_conn.cursor() as cursor:
                delete_sql = "DELETE FROM file_metadata WHERE id = %s"
                cursor.execute(delete_sql, (record['id'],))
                source_conn.commit()
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to migrate record {record['id']} (user {record['user_id']}): {e}")
        # ROLLBACK PROBLEM: Insert succeeded, delete failed
        # Now you have the record in BOTH shards!
        # You need compensating transactions or manual cleanup
        return False


def perform_migration():
    """
    Execute the full database resharding migration.
    
    Purpose:
        Move all records from old shards to new shards based on new routing.
    
    Consumers:
        Main script execution.
    
    Logic:
        1. Scan all records from shards 0 and 1 (old shards)
        2. For each record:
           - Calculate old shard (where it is now)
           - Calculate new shard (where it should be)
           - If different, migrate it
        3. Track statistics and report results
        
    WHY THIS IS SLOW AT SCALE:
    =========================
    - We process records one by one (safest but slowest)
    - Could batch, but batching increases complexity:
      - What if batch fails halfway?
      - How to track partial completion?
      - Rollback becomes nightmare
    
    Returns:
        dict: Migration statistics
    """
    logger.info("=" * 80)
    logger.info("STARTING DATABASE RESHARDING MIGRATION")
    logger.info("=" * 80)
    logger.info(f"Old strategy: user_id % {OLD_NUM_SHARDS}")
    logger.info(f"New strategy: user_id % {NEW_NUM_SHARDS}")
    logger.info("")
    logger.warning("⚠️  THIS SHOULD BE DONE WITH APPLICATION OFFLINE!")
    logger.warning("⚠️  ANY WRITES DURING MIGRATION WILL CAUSE DATA INCONSISTENCY!")
    logger.info("")
    
    # Wait for confirmation in production
    # time.sleep(5)
    
    # Statistics tracking
    stats = {
        "total_records_scanned": 0,
        "records_stayed": 0,
        "records_migrated": 0,
        "migration_failures": 0,
        "migrations_per_shard": {},
        "time_taken_seconds": 0
    }
    
    start_time = time.time()
    
    # Phase 1: Scan and migrate from old shards
    logger.info("Phase 1: Scanning existing data from old shards (0, 1)...")
    logger.info("")
    
    for old_shard_id in range(OLD_NUM_SHARDS):
        logger.info(f"Processing Shard {old_shard_id}...")
        
        try:
            with get_db_connection(old_shard_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    # Read all records from this shard
                    cursor.execute("""
                        SELECT id, user_id, file_name, created_at 
                        FROM file_metadata 
                        ORDER BY user_id
                    """)
                    records = cursor.fetchall()
                    
                    logger.info(f"  Found {len(records)} records in Shard {old_shard_id}")
                    
                    for record in records:
                        stats["total_records_scanned"] += 1
                        user_id = record['user_id']
                        
                        # Calculate where this record should be
                        old_shard = get_old_shard_id(user_id)
                        new_shard = get_new_shard_id(user_id)
                        
                        # Sanity check: verify record is in expected old shard
                        if old_shard != old_shard_id:
                            logger.warning(f"  ⚠️  Unexpected: User {user_id} in Shard {old_shard_id} but should be in {old_shard}")
                        
                        if old_shard == new_shard:
                            # Record stays in current shard
                            stats["records_stayed"] += 1
                            logger.debug(f"  ✓ User {user_id}: STAYS in Shard {old_shard}")
                        else:
                            # Record needs migration
                            logger.info(f"  → User {user_id}: MOVING from Shard {old_shard} to Shard {new_shard}")
                            
                            # Track migration paths
                            migration_key = f"{old_shard}→{new_shard}"
                            if migration_key not in stats["migrations_per_shard"]:
                                stats["migrations_per_shard"][migration_key] = 0
                            
                            # Perform the actual migration
                            # THIS IS THE CRITICAL SECTION
                            # In production, you'd want:
                            # - Row-level locks
                            # - Retry logic
                            # - Checkpoint/resume capability
                            # - Dead letter queue for failures
                            success = migrate_record(record, old_shard, new_shard)
                            
                            if success:
                                stats["records_migrated"] += 1
                                stats["migrations_per_shard"][migration_key] += 1
                                logger.info(f"    ✓ Migrated successfully")
                            else:
                                stats["migration_failures"] += 1
                                logger.error(f"    ✗ Migration failed!")
                        
                        # Progress indicator
                        if stats["total_records_scanned"] % 10 == 0:
                            logger.info(f"  Progress: {stats['total_records_scanned']} records processed...")
        
        except Exception as e:
            logger.error(f"Failed to process Shard {old_shard_id}: {e}")
            raise
    
    end_time = time.time()
    stats["time_taken_seconds"] = round(end_time - start_time, 2)
    
    # Print final report
    logger.info("")
    logger.info("=" * 80)
    logger.info("MIGRATION COMPLETE!")
    logger.info("=" * 80)
    logger.info("")
    logger.info("📊 FINAL STATISTICS:")
    logger.info(f"  Total records scanned: {stats['total_records_scanned']}")
    logger.info(f"  Records that stayed in place: {stats['records_stayed']} ({stats['records_stayed']/stats['total_records_scanned']*100:.1f}%)")
    logger.info(f"  Records that PHYSICALLY MOVED: {stats['records_migrated']} ({stats['records_migrated']/stats['total_records_scanned']*100:.1f}%)")
    logger.info(f"  Migration failures: {stats['migration_failures']}")
    logger.info(f"  Time taken: {stats['time_taken_seconds']} seconds")
    logger.info("")
    
    if stats["migrations_per_shard"]:
        logger.info("📦 MIGRATION BREAKDOWN:")
        for path, count in stats["migrations_per_shard"].items():
            logger.info(f"  {path}: {count} records")
    
    logger.info("")
    logger.info("💡 KEY INSIGHT:")
    logger.info(f"  Just by adding ONE new database (Shard 2),")
    logger.info(f"  we had to physically move {stats['records_migrated']} out of {stats['total_records_scanned']} records!")
    logger.info(f"  That's {stats['records_migrated']/stats['total_records_scanned']*100:.1f}% of your data!")
    logger.info("")
    logger.info("  With 1TB of data:")
    logger.info(f"  - ~{stats['records_migrated']/stats['total_records_scanned']*1000:.0f}GB would need to move")
    logger.info(f"  - At 100MB/s: ~{stats['records_migrated']/stats['total_records_scanned']*1000*10/60:.0f} minutes")
    logger.info(f"  - At 10MB/s: ~{stats['records_migrated']/stats['total_records_scanned']*1000*10/60/60:.1f} hours")
    logger.info(f"  - Plus time to DELETE from old shards")
    logger.info(f"  - Plus time to verify integrity")
    logger.info(f"  - TOTAL DOWNTIME: Likely 12-24 hours minimum")
    logger.info("")
    logger.info("=" * 80)
    
    return stats


def verify_migration():
    """
    Verify that migration completed successfully.
    
    Purpose:
        Ensure all records are in their correct shards after migration.
    
    Logic:
        1. Query all shards
        2. For each record, verify: actual_shard == (user_id % NEW_NUM_SHARDS)
        3. Report any misplaced records
    
    Returns:
        bool: True if all records are correctly placed
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("VERIFYING MIGRATION INTEGRITY")
    logger.info("=" * 80)
    
    total_records = 0
    misplaced_records = 0
    
    for shard_id in range(NEW_NUM_SHARDS):
        logger.info(f"Checking Shard {shard_id}...")
        
        try:
            with get_db_connection(shard_id) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SELECT id, user_id, file_name FROM file_metadata")
                    records = cursor.fetchall()
                    
                    logger.info(f"  Found {len(records)} records")
                    
                    for record in records:
                        total_records += 1
                        user_id = record['user_id']
                        expected_shard = get_new_shard_id(user_id)
                        
                        if expected_shard != shard_id:
                            misplaced_records += 1
                            logger.error(f"  ✗ User {user_id} in Shard {shard_id} but should be in Shard {expected_shard}")
                        else:
                            logger.debug(f"  ✓ User {user_id} correctly in Shard {shard_id}")
        
        except Exception as e:
            logger.error(f"Failed to verify Shard {shard_id}: {e}")
            return False
    
    logger.info("")
    logger.info(f"Verification complete: {total_records} records checked")
    
    if misplaced_records == 0:
        logger.info("✓ ALL RECORDS ARE CORRECTLY PLACED!")
        return True
    else:
        logger.error(f"✗ FOUND {misplaced_records} MISPLACED RECORDS!")
        return False


if __name__ == "__main__":
    logger.info("Database Resharding Migration Script")
    logger.info("====================================")
    logger.info("")
    
    try:
        # Perform migration
        stats = perform_migration()
        
        # Verify results
        if verify_migration():
            logger.info("")
            logger.info("✓ Migration completed successfully!")
            sys.exit(0)
        else:
            logger.error("")
            logger.error("✗ Migration completed with errors!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("Migration interrupted by user!")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
