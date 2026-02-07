"""
File sync business logic with optimistic concurrency control
"""
import hashlib
import logging
from datetime import datetime
from typing import Tuple, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import FileRecord
from src.services.storage import storage_service

logger = logging.getLogger(__name__)


def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content"""
    return hashlib.sha256(content).hexdigest()


class FileSyncService:
    """Business logic for file synchronization"""
    
    @staticmethod
    async def create_file(
        session: AsyncSession,
        file_id: str,
        content: bytes,
        mime_type: str = "application/octet-stream"
    ) -> Tuple[FileRecord, str]:
        """
        Create new file with content-addressed storage
        Returns: (FileRecord, storage_key)
        """
        computed_hash = compute_hash(content)
        storage_key = storage_service.generate_storage_key(computed_hash)
        
        # Upload to MinIO only if not already exists (deduplication!)
        if not storage_service.exists(storage_key):
            storage_service.upload(storage_key, content)
            logger.info(f"📤 Uploaded new content: {storage_key} ({len(content)} bytes)")
        else:
            logger.info(f"♻️ Content already exists, reusing: {storage_key}")
        
        # Create metadata record
        file_record = FileRecord(
            file_id=file_id,
            version=1,
            storage_key=storage_key,
            content_hash=computed_hash,
            size_bytes=len(content),
            mime_type=mime_type
        )
        session.add(file_record)
        await session.commit()
        
        logger.info(f"✅ Created {file_id} v1 (hash: {computed_hash[:8]})")
        return file_record, storage_key
    
    @staticmethod
    async def update_file_optimistic(
        session: AsyncSession,
        file_id: str,
        content: bytes,
        expected_version: int,
        content_hash_provided: Optional[str] = None
    ) -> Tuple[bool, Optional[FileRecord], Optional[str]]:
        """
        Update file with optimistic locking + content-addressed storage
        
        Returns: (success, file_record_or_conflict, storage_key)
        - If success: (True, updated_record, storage_key)
        - If conflict: (False, current_record, None)
        """
        computed_hash = compute_hash(content)
        new_version = expected_version + 1
        
        # Validate hash if provided
        if content_hash_provided and content_hash_provided != computed_hash:
            raise ValueError(f"Hash mismatch: expected {content_hash_provided}, got {computed_hash}")
        
        # Generate content-addressed storage key (just the hash)
        storage_key = storage_service.generate_storage_key(computed_hash)
        
        # Upload to MinIO only if not exists (deduplication!)
        if not storage_service.exists(storage_key):
            storage_service.upload(storage_key, content)
            logger.info(f"📤 Uploaded new content: {storage_key} ({len(content)} bytes)")
        else:
            logger.info(f"♻️ Content already exists, reusing: {storage_key}")
        
        # TRUE OPTIMISTIC LOCKING: Atomic UPDATE with WHERE version check
        stmt = (
            update(FileRecord)
            .where(
                FileRecord.file_id == file_id,
                FileRecord.version == expected_version  # Atomic version check
            )
            .values(
                storage_key=storage_key,
                version=new_version,
                content_hash=computed_hash,
                size_bytes=len(content),
                updated_at=datetime.utcnow()
            )
        )
        
        result = await session.execute(stmt)
        await session.commit()
        
        # Check if update actually happened (rowcount == 0 means version mismatch)
        if result.rowcount == 0:
            # CONFLICT! Content already in storage (may be used by other files)
            # So we DON'T delete it - just return conflict
            
            logger.warning(f"⚠️ CONFLICT for {file_id}: expected v{expected_version}")
            
            # Fetch current state
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            current_file = result.scalar_one()
            return False, current_file, None
        
        # Success!
        logger.info(f"✅ Updated {file_id}: v{expected_version} → v{new_version} (hash: {computed_hash[:8]})")
        
        # Fetch updated record
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        updated_file = result.scalar_one()
        return True, updated_file, storage_key
    
    @staticmethod
    async def get_file(session: AsyncSession, file_id: str) -> Optional[FileRecord]:
        """Get file metadata"""
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_file_content(file_record: FileRecord) -> bytes:
        """Download file content from storage"""
        return storage_service.download(file_record.storage_key)
    
    @staticmethod
    async def delete_file(session: AsyncSession, file_id: str) -> bool:
        """
        Delete file (metadata only - content stays in storage)
        
        With content-addressed storage, we don't delete content immediately
        because other files may reference the same hash.
        
        Note: In production, you'd run garbage collection periodically
        to clean up unreferenced content.
        """
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            return False
        
        # Delete metadata only (content may be shared with other files)
        await session.delete(file_record)
        await session.commit()
        
        logger.info(f"✅ Deleted {file_id} metadata (content {file_record.content_hash[:8]} may be shared)")
        return True
    
    @staticmethod
    async def list_all_files(session: AsyncSession) -> list[FileRecord]:
        """List all files"""
        result = await session.execute(select(FileRecord))
        return list(result.scalars().all())
