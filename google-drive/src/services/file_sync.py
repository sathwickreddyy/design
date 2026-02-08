"""
File sync business logic with optimistic concurrency control
"""
import hashlib
import logging
from datetime import datetime
from typing import Tuple, Optional, AsyncIterator
import io

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FileRecord
from .storage import storage_service

logger = logging.getLogger(__name__)


async def compute_hash_streaming(content_stream: AsyncIterator[bytes]) -> str:
    """
    Compute SHA256 hash from streaming content
    
    Efficiently hashes large files without loading into memory:
    - Process in chunks (8KB)
    - Single pass (compute while reading)
    - Works for any file size
    """
    hasher = hashlib.sha256()
    
    async for chunk in content_stream:
        hasher.update(chunk)
    
    return hasher.hexdigest()


def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content (for small payloads)"""
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
        Create new file with content-addressed storage (non-streaming)
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
    async def create_file_streaming(
        session: AsyncSession,
        file_id: str,
        content_stream: AsyncIterator[bytes],
        mime_type: str = "application/octet-stream"
    ) -> Tuple[FileRecord, str]:
        """
        Create new file with streaming upload (production-grade)
        
        Hash is computed while streaming - single pass, constant memory!
        Returns: (FileRecord, storage_key)
        """
        # Stream to temporary storage, computing hash in parallel
        temp_storage_key = f"temp/{file_id}"
        content_hash, size_bytes = await storage_service.upload_streaming(
            temp_storage_key, 
            content_stream
        )
        
        # Now we know the hash, generate final storage key
        storage_key = storage_service.generate_storage_key(content_hash)
        
        # Check if content already exists (deduplication!)
        if storage_service.exists(storage_key):
            # Delete temp, reuse existing
            storage_service.delete(temp_storage_key)
            logger.info(f"♻️ Content already exists, reusing: {storage_key}")
        else:
            # Move temp to final location (or keep temp as final if hash matches)
            if temp_storage_key != storage_key:
                # Copy to content-addressed location
                content = storage_service.download(temp_storage_key)
                storage_service.upload(storage_key, content)
                storage_service.delete(temp_storage_key)
            logger.info(f"📤 Uploaded new streaming content: {storage_key} ({size_bytes} bytes)")
        
        # Create metadata record
        file_record = FileRecord(
            file_id=file_id,
            version=1,
            storage_key=storage_key,
            content_hash=content_hash,
            size_bytes=size_bytes,
            mime_type=mime_type
        )
        session.add(file_record)
        await session.commit()
        
        logger.info(f"✅ Created {file_id} v1 (streaming, hash: {content_hash[:8]})")
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
        
        Flow:
        1. Compute hash of new content
        2. Check version FIRST (atomic, before uploading)
        3. Only if version matches → upload to MinIO
        4. If conflict → no upload (efficient!)
        
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
        
        # **STEP 1: Atomic version check FIRST (before any upload)**
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
            # CONFLICT! No upload needed (efficient!)
            logger.warning(f"⚠️ CONFLICT for {file_id}: expected v{expected_version}")
            
            # Fetch current state
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            current_file = result.scalar_one()
            return False, current_file, None
        
        # **STEP 2: Only upload to MinIO if version check PASSED**
        # Content-addressed: skip upload if already exists (deduplication!)
        if not storage_service.exists(storage_key):
            storage_service.upload(storage_key, content)
            logger.info(f"📤 Uploaded new content: {storage_key} ({len(content)} bytes)")
        else:
            logger.info(f"♻️ Content already exists, reusing: {storage_key}")
        
        # Success!
        logger.info(f"✅ Updated {file_id}: v{expected_version} → v{new_version} (hash: {computed_hash[:8]})")
        
        # Fetch updated record
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        updated_file = result.scalar_one()
        return True, updated_file, storage_key
    
    @staticmethod
    async def update_file_optimistic_streaming(
        session: AsyncSession,
        file_id: str,
        content_stream: AsyncIterator[bytes],
        expected_version: int
    ) -> Tuple[bool, Optional[FileRecord], Optional[str]]:
        """
        Update file with optimistic locking + streaming (production-grade!)
        
        Flow:
        1. Check version FIRST (metadata check, cheap)
        2. Stream upload to temp location (hash computed during upload)
        3. Move to content-addressed location (or reuse if exists)
        4. Update metadata
        
        Returns: (success, file_record_or_conflict, storage_key)
        - If success: (True, updated_record, storage_key)
        - If conflict: (False, current_record, None)
        """
        # **STEP 1: Check version FIRST (before streaming)**
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            raise ValueError(f"File {file_id} not found")
        
        if existing.version != expected_version:
            logger.warning(f"⚠️ CONFLICT for {file_id}: expected v{expected_version}, current v{existing.version}")
            return False, existing, None
        
        # **STEP 2: Stream to temp location (hash computed in parallel)**
        new_version = expected_version + 1
        temp_storage_key = f"temp/{file_id}_v{new_version}"
        content_hash, size_bytes = await storage_service.upload_streaming(
            temp_storage_key,
            content_stream
        )
        
        # **STEP 3: Generate content-addressed key and handle deduplication**
        storage_key = storage_service.generate_storage_key(content_hash)
        
        if storage_service.exists(storage_key):
            # Delete temp, reuse existing
            storage_service.delete(temp_storage_key)
            logger.info(f"♻️ Content already exists, reusing: {storage_key}")
        else:
            # Move temp to final content-addressed location
            if temp_storage_key != storage_key:
                content = storage_service.download(temp_storage_key)
                storage_service.upload(storage_key, content)
                storage_service.delete(temp_storage_key)
            logger.info(f"📤 Uploaded new streaming content: {storage_key} ({size_bytes} bytes)")
        
        # **STEP 4: Update metadata with version increment**
        stmt = (
            update(FileRecord)
            .where(
                FileRecord.file_id == file_id,
                FileRecord.version == expected_version  # Double-check version hasn't changed
            )
            .values(
                storage_key=storage_key,
                version=new_version,
                content_hash=content_hash,
                size_bytes=size_bytes,
                updated_at=datetime.utcnow()
            )
        )
        
        result = await session.execute(stmt)
        await session.commit()
        
        if result.rowcount == 0:
            # Race condition: version changed during upload
            # Clean up uploaded content (if unique)
            logger.error(f"❌ Race condition for {file_id}: version changed during upload")
            # Note: In production, you'd have garbage collection handle this
            
            # Return current state
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            current_file = result.scalar_one()
            return False, current_file, None
        
        # Success!
        logger.info(f"✅ Updated {file_id}: v{expected_version} → v{new_version} (streaming, hash: {content_hash[:8]})")
        
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
