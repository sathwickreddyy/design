"""
File synchronization service with hierarchical operations and OCC
"""
import logging
from typing import Optional, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FileRecord, FileVersionHistory
from .storage import storage_service

logger = logging.getLogger(__name__)


class FileSyncService:
    """
    Business logic for hierarchical file operations with optimistic concurrency control.
    
    Features:
    - Hierarchical folder/file operations (parent_id based)
    - Per-file version tracking (optimistic locking)
    - Streaming uploads with hash computation
    - Version history tracking
    - Content deduplication via hash-based storage
    """
    
    @staticmethod
    async def get_file(session: AsyncSession, file_id: int) -> Optional[FileRecord]:
        """Get file/folder by ID"""
        return await session.get(FileRecord, file_id)
    
    @staticmethod
    async def list_children(
        session: AsyncSession,
        parent_id: Optional[int],
        folders_first: bool = True
    ) -> list[FileRecord]:
        """
        List direct children of a folder (or root if parent_id=None).
        
        Args:
            parent_id: Parent folder ID (None for root)
            folders_first: Sort folders before files
            
        Returns:
            List of FileRecord objects (folders first, then files, alphabetically)
        """
        query = select(FileRecord).where(FileRecord.parent_id == parent_id)
        
        if folders_first:
            query = query.order_by(
                FileRecord.is_folder.desc(),  # Folders first
                FileRecord.name.asc()  # Then alphabetically
            )
        else:
            query = query.order_by(FileRecord.name.asc())
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def create_folder(
        session: AsyncSession,
        name: str,
        parent_id: Optional[int] = None
    ) -> FileRecord:
        """
        Create a new folder.
        
        Args:
            name: Folder name
            parent_id: Parent folder ID (None for root)
            
        Returns:
            Created FileRecord
        """
        # Verify parent exists if specified
        if parent_id is not None:
            parent = await session.get(FileRecord, parent_id)
            if not parent:
                raise ValueError(f"Parent folder {parent_id} not found")
            if not parent.is_folder:
                raise ValueError(f"Parent {parent_id} is not a folder")
        
        folder = FileRecord(
            name=name,
            parent_id=parent_id,
            is_folder=True,
            version=1
        )
        
        session.add(folder)
        await session.flush()  # Get ID
        await session.commit()
        
        logger.info(f"📁 Created folder: id={folder.id} name={name} parent_id={parent_id}")
        return folder
    
    @staticmethod
    async def create_file_streaming(
        session: AsyncSession,
        name: str,
        parent_id: Optional[int],
        content_stream: AsyncIterator[bytes],
        mime_type: str
    ) -> FileRecord:
        """
        Create new file with streaming upload.
        
        Process:
        1. Upload to MinIO (compute hash)
        2. Create database record
        
        Args:
            name: File name
            parent_id: Parent folder ID (None for root)
            content_stream: Async iterator of file chunks
            mime_type: MIME type
            
        Returns:
            Created FileRecord
        """
        # Verify parent exists if specified
        if parent_id is not None:
            parent = await session.get(FileRecord, parent_id)
            if not parent:
                raise ValueError(f"Parent folder {parent_id} not found")
            if not parent.is_folder:
                raise ValueError(f"Parent {parent_id} is not a folder")
        
        # Upload to MinIO and compute hash
        temp_key = f"uploads/temp_{name}"
        content_hash, size_bytes = await storage_service.upload_streaming(
            temp_key,
            content_stream
        )
        
        # Create file record
        file_record = FileRecord(
            name=name,
            parent_id=parent_id,
            is_folder=False,
            version=1,
            content_hash=content_hash,
            size_bytes=size_bytes,
            mime_type=mime_type
        )
        
        session.add(file_record)
        await session.flush()
        await session.commit()
        
        logger.info(f"📄 Created file: id={file_record.id} name={name} hash={content_hash[:8]}... size={size_bytes}")
        return file_record
    
    @staticmethod
    async def update_file_optimistic_streaming(
        session: AsyncSession,
        file_id: int,
        content_stream: AsyncIterator[bytes],
        expected_version: int
    ) -> tuple[bool, FileRecord]:
        """
        Update file with optimistic concurrency control (streaming).
        
        Process:
        1. Check version matches (fail fast if conflict)
        2. Save current version to history
        3. Upload new content
        4. Update record atomically
        
        Args:
            file_id: File ID to update
            content_stream: New content
            expected_version: Expected current version
            
        Returns:
            (success: bool, file_record: FileRecord)
            If success=False, file_record contains current conflicting state
        """
        # Get current file
        file_record = await session.get(FileRecord, file_id)
        if not file_record:
            raise ValueError(f"File {file_id} not found")
        
        if file_record.is_folder:
            raise ValueError(f"Cannot update folder {file_id} as file")
        
        # Check version (optimistic locking)
        if file_record.version != expected_version:
            logger.warning(
                f"⚠️  Version conflict: file {file_id} expected v{expected_version}, "
                f"got v{file_record.version}"
            )
            return False, file_record
        
        # Save current version to history
        await FileSyncService._save_to_version_history(
            session,
            file_id=file_record.id,
            name=file_record.name,
            version=file_record.version,
            content_hash=file_record.content_hash,
            size_bytes=file_record.size_bytes,
            mime_type=file_record.mime_type
        )
        
        # Upload new content
        temp_key = f"uploads/temp_{file_id}"
        content_hash, size_bytes = await storage_service.upload_streaming(
            temp_key,
            content_stream
        )
        
        # Update file record
        file_record.content_hash = content_hash
        file_record.size_bytes = size_bytes
        file_record.version += 1
        
        await session.commit()
        
        logger.info(
            f"✅ Updated file: id={file_id} v{expected_version}→v{file_record.version} "
            f"hash={content_hash[:8]}..."
        )
        return True, file_record
    
    @staticmethod
    async def _save_to_version_history(
        session: AsyncSession,
        file_id: int,
        name: str,
        version: int,
        content_hash: str,
        size_bytes: int,
        mime_type: str
    ):
        """Save file version to history table"""
        history_entry = FileVersionHistory(
            file_id=file_id,
            name=name,
            version=version,
            content_hash=content_hash,
            size_bytes=size_bytes,
            mime_type=mime_type
        )
        
        session.add(history_entry)
        await session.flush()
        logger.info(f"📚 Saved version history: file_id={file_id} v{version}")
    
    @staticmethod
    async def get_file_content(file_record: FileRecord) -> bytes:
        """Download file content from storage"""
        if file_record.is_folder:
            raise ValueError("Cannot download folder content")
        
        if not file_record.storage_key:
            raise ValueError("File has no storage key")
        
        return storage_service.download(file_record.storage_key)
    
    @staticmethod
    async def delete_file(session: AsyncSession, file_id: int) -> bool:
        """
        Delete file/folder (soft delete - only removes metadata).
        
        Note: Actual content in MinIO is NOT deleted (enables deduplication).
        For folders, deletes recursively via CASCADE.
        
        Returns:
            True if deleted, False if not found
        """
        file_record = await session.get(FileRecord, file_id)
        if not file_record:
            return False
        
        await session.delete(file_record)
        await session.commit()
        
        marker = "📁" if file_record.is_folder else "📄"
        logger.info(f"🗑️  Deleted: {marker} id={file_id} name={file_record.name}")
        return True
    
    @staticmethod
    async def move_file(
        session: AsyncSession,
        file_id: int,
        new_parent_id: Optional[int]
    ) -> FileRecord:
        """
        Move file/folder to different parent.
        
        Args:
            file_id: File/folder to move
            new_parent_id: New parent folder ID (None for root)
            
        Returns:
            Updated FileRecord
        """
        file_record = await session.get(FileRecord, file_id)
        if not file_record:
            raise ValueError(f"File {file_id} not found")
        
        # Verify new parent exists and is a folder
        if new_parent_id is not None:
            new_parent = await session.get(FileRecord, new_parent_id)
            if not new_parent:
                raise ValueError(f"Parent folder {new_parent_id} not found")
            if not new_parent.is_folder:
                raise ValueError(f"Parent {new_parent_id} is not a folder")
            
            # Prevent moving folder into itself or descendant
            if file_record.is_folder:
                if new_parent_id == file_id:
                    raise ValueError("Cannot move folder into itself")
        
        old_parent_id = file_record.parent_id
        file_record.parent_id = new_parent_id
        
        await session.commit()
        
        logger.info(f"🔄 Moved id={file_id} from parent={old_parent_id} to parent={new_parent_id}")
        return file_record
    
    @staticmethod
    async def rename_file(
        session: AsyncSession,
        file_id: int,
        new_name: str
    ) -> FileRecord:
        """
        Rename file/folder.
        
        Args:
            file_id: File/folder ID
            new_name: New name
            
        Returns:
            Updated FileRecord
        """
        file_record = await session.get(FileRecord, file_id)
        if not file_record:
            raise ValueError(f"File {file_id} not found")
        
        old_name = file_record.name
        file_record.name = new_name
        
        await session.commit()
        
        logger.info(f"✏️  Renamed id={file_id} from '{old_name}' to '{new_name}'")
        return file_record
    
    @staticmethod
    async def get_version_history(
        session: AsyncSession,
        file_id: int
    ) -> list[FileVersionHistory]:
        """Get all historical versions of a file"""
        result = await session.execute(
            select(FileVersionHistory)
            .where(FileVersionHistory.file_id == file_id)
            .order_by(FileVersionHistory.version.asc())
        )
        return list(result.scalars().all())
