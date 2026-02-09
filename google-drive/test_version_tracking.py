#!/usr/bin/env python
"""
Test version history tracking with 3 file uploads
"""
import asyncio
import logging
from sqlalchemy import select

from src.core.config import settings
from src.core.database import engine, async_session_maker, Base
from src.models import FileRecord, FileVersionHistory
from src.services import FileSyncService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_version_tracking():
    """Test uploading 3 versions of same file and tracking history"""
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables created")
    
    # Create test file (will be overridden)
    file_id = "report.txt"
    
    async with async_session_maker() as session:
        # Version 1: Initial upload
        logger.info("\n📤 Uploading Version 1...")
        v1_content = b"Initial report content"
        file_v1, storage_key_v1 = await FileSyncService.create_file(
            session, file_id, v1_content, "text/plain"
        )
        logger.info(f"✅ V1: {file_v1.version} (hash: {file_v1.content_hash[:8]})")
        
        # Version 2: First update
        logger.info("\n📤 Uploading Version 2...")
        v2_content = b"Initial report content - Updated with more data"
        success, file_v2, storage_key_v2 = await FileSyncService.update_file_optimistic(
            session, file_id, v2_content, expected_version=1
        )
        assert success, "V2 update should succeed"
        logger.info(f"✅ V2: {file_v2.version} (hash: {file_v2.content_hash[:8]})")
        
        # Version 3: Second update
        logger.info("\n📤 Uploading Version 3...")
        v3_content = b"Initial report content - Updated with more data - Final version"
        success, file_v3, storage_key_v3 = await FileSyncService.update_file_optimistic(
            session, file_id, v3_content, expected_version=2
        )
        assert success, "V3 update should succeed"
        logger.info(f"✅ V3: {file_v3.version} (hash: {file_v3.content_hash[:8]})")
        
        # Query current file
        current = await FileSyncService.get_file(session, file_id)
        logger.info(f"\n🔍 Current file state:")
        logger.info(f"   File ID: {current.file_id}")
        logger.info(f"   Current Version: {current.version}")
        logger.info(f"   Content Hash: {current.content_hash[:8]}")
        logger.info(f"   Size: {current.size_bytes} bytes")
        
        # Query version history
        logger.info(f"\n📚 Version History:")
        result = await session.execute(
            select(FileVersionHistory)
            .where(FileVersionHistory.file_id == file_id)
            .order_by(FileVersionHistory.version.asc())
        )
        history = result.scalars().all()
        
        for entry in history:
            logger.info(
                f"   V{entry.version}: {entry.content_hash[:8]} "
                f"({entry.size_bytes} bytes) - {entry.created_at}"
            )
        
        # Verify counts
        assert current.version == 3, "Should be at version 3"
        assert len(history) == 2, "Should have 2 historical versions (V1, V2)"
        
        logger.info(f"\n✅ Version tracking works! Current version: {current.version}, History: {len(history)} entries")
        
        # Test conflict detection
        logger.info(f"\n⚠️ Testing conflict detection...")
        try:
            success, _, _ = await FileSyncService.update_file_optimistic(
                session, file_id, b"conflict content", expected_version=1  # Wrong version!
            )
            assert not success, "Should detect version conflict"
            logger.info("✅ Conflict detected correctly!")
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(test_version_tracking())
