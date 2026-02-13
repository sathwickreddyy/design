"""
File synchronization service with hierarchical operations and multi-user support
"""
import logging
from typing import Optional, AsyncIterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FileRecord, FileVersionHistory
from .storage import storage_service

logger = logging.getLogger(__name__)


class FileSyncService:
    """
    Business logic for hierarchical file operations with multi-user sharding.
    
    Sharding Strategy:
    - Shard key: user_id (all user's files on same shard)
    - Each user has root_id (their "My Drive" folder)
    - Version tracking per file (not folders)
    - History denormalizes user_id for co-location
    """
    
    @staticmethod
    async def get_file(session: AsyncSession, file_id: str, user_id: str) -> Optional[FileRecord]:
        """
        Get file/folder by ID with user ownership validation.
        
        Args:
            file_id: File UUID
            user_id: Owner's user ID
            
        Returns:
            FileRecord if found and owned by user, else None
        """
        logger.debug(f"🔍 FLOW: get_file() - Checking ownership: file_id={file_id}, user_id={user_id}")
        
        # Query with shard key + file_id (single-shard lookup)
        logger.debug(f"  ✓ VALIDATION: Querying database with user_id as shard key")
        result = await session.execute(
            select(FileRecord)
            .where(FileRecord.id == file_id)
            .where(FileRecord.user_id == user_id)
        )
        file_record = result.scalar_one_or_none()
        
        if file_record:
            marker = "📁" if file_record.is_folder else "📄"
            logger.debug(f"  ✓ RESULT: Found {marker} {file_record.name} (v{file_record.version})")
            logger.debug(f"  ✓ RETURN: FileRecord(id={file_record.id}, user_id={user_id})")
        else:
            logger.debug(f"  ✗ RESULT: File not found or ownership failed")
            logger.debug(f"  ✓ RETURN: None (unauthorized or not exists)")
        
        return file_record
    
    @staticmethod
    async def list_children(
        session: AsyncSession,
        user_id: str,
        parent_id: Optional[str],
        folders_first: bool = True
    ) -> list[FileRecord]:
        """
        List direct children of a folder (single-shard query).
        
        Args:
            user_id: Owner's user ID (shard key)
            parent_id: Parent folder ID (None for root)
            folders_first: Sort folders before files
            
        Returns:
            List of FileRecord objects owned by user
        """
        parent_label = "root" if parent_id is None else parent_id
        logger.info(f"📂 FLOW: list_children() - Listing {parent_label} for user_id={user_id}")
        
        # Build query with shard key
        logger.debug(f"  ✓ VALIDATION: Using user_id={user_id} as shard key (single-shard query)")
        logger.debug(f"  ✓ VALIDATION: Filtering by parent_id={parent_id}")
        
        query = (
            select(FileRecord)
            .where(FileRecord.user_id == user_id)
            .where(FileRecord.parent_id == parent_id)
        )
        
        # Apply sorting
        if folders_first:
            logger.debug(f"  ✓ TRANSFORM: Sorting folders first, then alphabetically")
            query = query.order_by(
                FileRecord.is_folder.desc(),
                FileRecord.name
            )
        else:
            logger.debug(f"  ✓ TRANSFORM: Sorting alphabetically")
            query = query.order_by(FileRecord.name)
        
        result = await session.execute(query)
        items = list(result.scalars().all())
        
        folders_count = sum(1 for item in items if item.is_folder)
        files_count = len(items) - folders_count
        logger.info(f"  ✓ RESULT: {len(items)} items ({folders_count} folders, {files_count} files)")
        logger.debug(f"  ✓ RETURN: list[FileRecord] with {len(items)} items")
        
        return items
    
    @staticmethod
    async def create_folder(
        session: AsyncSession,
        name: str,
        user_id: str,
        parent_id: Optional[str] = None
    ) -> FileRecord:
        """
        Create a new folder.
        
        If parent_id is None, creates at root level.
        Sets root_id to self if creating root, else inherits from parent.
        
        Args:
            name: Folder name
            user_id: Owner's user ID
            parent_id: Parent folder ID (None for root)
            
        Returns:
            Created FileRecord
        """
        logger.info(f"📁 FLOW: create_folder() - Creating folder '{name}' for user_id={user_id}")
        logger.debug(f"  ✓ INPUT: name='{name}', parent_id={parent_id}")
        
        # Validate parent exists if specified
        if parent_id:
            logger.debug(f"  ✓ VALIDATION: Checking parent folder exists: {parent_id}")
            parent = await session.get(FileRecord, parent_id)
            
            if not parent:
                logger.error(f"  ✗ VALIDATION FAILED: Parent folder {parent_id} not found")
                raise ValueError(f"Parent folder {parent_id} not found")
            
            logger.debug(f"  ✓ VALIDATION: Checking parent ownership (user_id={parent.user_id} vs {user_id})")
            if parent.user_id != user_id:
                logger.error(f"  ✗ VALIDATION FAILED: Parent owned by different user ({parent.user_id})")
                raise ValueError("Cannot create folder in another user's directory")
            
            logger.debug(f"  ✓ VALIDATION: Checking parent is folder (is_folder={parent.is_folder})")
            if not parent.is_folder:
                logger.error(f"  ✗ VALIDATION FAILED: Parent is not a folder")
                raise ValueError("Parent must be a folder")
            
            root_id = parent.root_id
            logger.debug(f"  ✓ INHERIT: root_id from parent: {root_id}")
        else:
            logger.debug(f"  ✓ VALIDATION: Creating at root level (parent_id=None)")
            root_id = None  # Will be set to self.id after creation
        
        # Generate UUID and create folder record
        folder_id = str(uuid4())
        logger.debug(f"  ✓ TRANSFORM: Generated folder_id={folder_id[:8]}...")
        
        folder = FileRecord(
            id=folder_id,
            name=name,
            parent_id=parent_id,
            user_id=user_id,
            root_id=root_id or folder_id,  # Self-reference for root
            is_folder=True,
            version=1,
            content_hash=None,
            size_bytes=None,
            mime_type=None
        )
        
        logger.debug(f"  ✓ TRANSFORM: Created FileRecord(root_id={folder.root_id})")
        
        session.add(folder)
        await session.flush()
        
        logger.info(f"  ✓ RESULT: Folder created in database")
        logger.info(f"  ✓ RETURN: FileRecord(id={folder.id}, root_id={folder.root_id}, version=1)")
        return folder
    
    @staticmethod
    async def create_file_streaming(
        session: AsyncSession,
        name: str,
        user_id: str,
        content_stream: AsyncIterator[bytes],
        parent_id: Optional[str],
        mime_type: str = "application/octet-stream"
    ) -> FileRecord:
        """
        Create new file with streaming upload.
        
        Args:
            name: File name
            user_id: Owner's user ID
            content_stream: Async byte stream
            parent_id: Parent folder ID
            mime_type: MIME type
            
        Returns:
            Created FileRecord
        """
        logger.info(f"📄 FLOW: create_file_streaming() - Uploading '{name}' to user_id={user_id}")
        logger.debug(f"  ✓ INPUT: name='{name}', parent_id={parent_id}, mime_type={mime_type}")
        
        # Validate parent
        if parent_id:
            logger.debug(f"  ✓ VALIDATION: Checking parent folder: {parent_id}")
            parent = await session.get(FileRecord, parent_id)
            
            if not parent:
                logger.error(f"  ✗ VALIDATION FAILED: Parent folder {parent_id} not found")
                raise ValueError(f"Parent folder {parent_id} not found")
            
            logger.debug(f"  ✓ VALIDATION: Checking parent ownership (user_id={parent.user_id} vs {user_id})")
            if parent.user_id != user_id:
                logger.error(f"  ✗ VALIDATION FAILED: Parent owned by different user")
                raise ValueError("Cannot create file in another user's directory")
            
            logger.debug(f"  ✓ VALIDATION: Checking parent is folder (is_folder={parent.is_folder})")
            if not parent.is_folder:
                logger.error(f"  ✗ VALIDATION FAILED: Parent is not a folder")
                raise ValueError("Parent must be a folder")
            
            root_id = parent.root_id
            logger.debug(f"  ✓ INHERIT: root_id from parent: {root_id}")
        else:
            logger.error(f"  ✗ VALIDATION FAILED: Files must have a parent folder")
            raise ValueError("Files must have a parent folder")
        
        # Upload to storage (computes hash, checks dedup)
        logger.info(f"  → TRANSFORM: Streaming file to storage service...")
        content_hash, size_bytes, storage_key = await storage_service.upload_streaming(
            f"temp/{str(uuid4())}",  # Temp key (real key computed from hash)
            content_stream
        )
        logger.info(f"  ✓ RESULT: Upload complete - hash={content_hash[:8]}..., size={size_bytes} bytes")
        
        # Create file record
        file_id = str(uuid4())
        logger.debug(f"  ✓ TRANSFORM: Generated file_id={file_id[:8]}...")
        
        file_record = FileRecord(
            id=file_id,
            name=name,
            parent_id=parent_id,
            user_id=user_id,
            root_id=root_id,
            is_folder=False,
            version=1,
            content_hash=content_hash,
            size_bytes=size_bytes,
            mime_type=mime_type
        )
        
        logger.debug(f"  ✓ TRANSFORM: Created FileRecord(root_id={root_id}, version=1)")
        
        session.add(file_record)
        await session.flush()
        
        logger.info(f"  ✓ RESULT: File metadata saved to database")
        logger.info(f"  ✓ RETURN: FileRecord(id={file_id[:8]}..., size={size_bytes} bytes, v1)")
        return file_record
    
    @staticmethod
    async def update_file_optimistic_streaming(
        session: AsyncSession,
        file_id: str,
        user_id: str,
        content_stream: AsyncIterator[bytes],
        expected_version: int,
        mime_type: Optional[str] = None
    ) -> FileRecord:
        """
        Update file content with optimistic concurrency control.
        
        Args:
            file_id: File UUID
            user_id: Owner's user ID
            content_stream: New content
            expected_version: Expected current version (OCC)
            mime_type: Optional new MIME type
            
        Returns:
            Updated FileRecord
            
        Raises:
            ValueError: If version mismatch or not owner
        """
        logger.info(f"🔄 FLOW: update_file_optimistic_streaming() - Updating file_id={file_id[:8]}...")
        logger.debug(f"  ✓ INPUT: user_id={user_id}, expected_version={expected_version}")
        
        # Get file with user validation
        logger.debug(f"  ✓ VALIDATION: Checking file ownership and existence...")
        file_record = await FileSyncService.get_file(session, file_id, user_id)
        if not file_record:
            logger.error(f"  ✗ VALIDATION FAILED: File not found or not owned by user")
            raise ValueError(f"File {file_id} not found or not owned by user")
        
        logger.debug(f"  ✓ VALIDATION: File found - {file_record.name}")
        logger.debug(f"  ✓ VALIDATION: Checking if file (not folder)...")
        if file_record.is_folder:
            logger.error(f"  ✗ VALIDATION FAILED: Cannot update folder content")
            raise ValueError("Cannot update folder content")
        
        # OCC check
        logger.debug(f"  ✓ VALIDATION: OCC check - current_version={file_record.version} vs expected={expected_version}")
        if file_record.version != expected_version:
            logger.warning(f"  ✗ VALIDATION FAILED: Version conflict detected (concurrent edit)")
            raise ValueError(
                f"Version conflict: expected {expected_version}, "
                f"current {file_record.version}"
            )
        
        # Save current version to history (denormalize user_id for sharding)
        logger.debug(f"  ✓ TRANSFORM: Archiving current version to history...")
        history = FileVersionHistory(
            version_id=str(uuid4()),
            file_id=file_record.id,
            parent_id=file_record.parent_id,
            user_id=file_record.user_id,  # Denormalized for co-location with user's files
            name=file_record.name,
            version=file_record.version,
            content_hash=file_record.content_hash,
            size_bytes=file_record.size_bytes,
            mime_type=file_record.mime_type
        )
        session.add(history)
        logger.debug(f"  ✓ RESULT: Version {file_record.version} archived (denormalized user_id={user_id})")
        
        # Upload new content
        logger.info(f"  → TRANSFORM: Streaming new content to storage...")
        content_hash, size_bytes, storage_key = await storage_service.upload_streaming(
            f"temp/{str(uuid4())}",  # Temp key (real key computed from hash)
            content_stream
        )
        logger.info(f"  ✓ RESULT: New content uploaded - hash={content_hash[:8]}..., size={size_bytes} bytes")
        
        # Update file record
        logger.debug(f"  ✓ TRANSFORM: Incrementing version: v{file_record.version}→v{file_record.version + 1}")
        file_record.content_hash = content_hash
        file_record.size_bytes = size_bytes
        file_record.version += 1
        if mime_type:
            logger.debug(f"  ✓ TRANSFORM: Updated mime_type={mime_type}")
            file_record.mime_type = mime_type
        
        await session.flush()
        
        logger.info(f"  ✓ RESULT: File metadata updated in database")
        logger.info(f"  ✓ RETURN: FileRecord(id={file_id[:8]}..., v{expected_version}→v{file_record.version})")
        return file_record
    
    @staticmethod
    async def move_file(
        session: AsyncSession,
        file_id: str,
        user_id: str,
        new_parent_id: Optional[str]
    ) -> FileRecord:
        """
        Move file/folder to different parent.
        
        Note: Cross-shard moves (changing user_id) not supported.
        
        Args:
            file_id: File/folder UUID
            user_id: Owner's user ID
            new_parent_id: New parent folder ID
            
        Returns:
            Updated FileRecord
        """
        logger.info(f"📦 FLOW: move_file() - Moving item for user_id={user_id}")
        logger.debug(f"  ✓ INPUT: file_id={file_id[:8]}..., new_parent_id={new_parent_id}")
        
        # Get file with user validation
        logger.debug(f"  ✓ VALIDATION: Checking file ownership...")
        file_record = await FileSyncService.get_file(session, file_id, user_id)
        if not file_record:
            logger.error(f"  ✗ VALIDATION FAILED: File not found or not owned by user")
            raise ValueError(f"File {file_id} not found or not owned by user")
        
        logger.debug(f"  ✓ RESULT: Found {file_record.name}")
        
        # Validate new parent
        if new_parent_id:
            logger.debug(f"  ✓ VALIDATION: Checking new parent folder: {new_parent_id[:8]}...")
            new_parent = await session.get(FileRecord, new_parent_id)
            
            if not new_parent:
                logger.error(f"  ✗ VALIDATION FAILED: New parent {new_parent_id} not found")
                raise ValueError(f"New parent {new_parent_id} not found")
            
            logger.debug(f"  ✓ VALIDATION: Checking new parent ownership (user_id={new_parent.user_id} vs {user_id})")
            if new_parent.user_id != user_id:
                logger.error(f"  ✗ VALIDATION FAILED: New parent owned by different user")
                raise ValueError("Cannot move to another user's folder")
            
            logger.debug(f"  ✓ VALIDATION: Checking new parent is folder (is_folder={new_parent.is_folder})")
            if not new_parent.is_folder:
                logger.error(f"  ✗ VALIDATION FAILED: New parent is not a folder")
                raise ValueError("New parent must be a folder")
            
            # Prevent moving folder into itself
            logger.debug(f"  ✓ VALIDATION: Checking circular move prevention...")
            if file_record.is_folder and new_parent_id == file_id:
                logger.error(f"  ✗ VALIDATION FAILED: Circular move detected (folder into itself)")
                raise ValueError("Cannot move folder into itself")
        else:
            logger.debug(f"  ✓ VALIDATION: Moving to root (parent_id=None)")
        
        # Update parent reference
        old_parent_id = file_record.parent_id
        file_record.parent_id = new_parent_id
        
        logger.debug(f"  ✓ TRANSFORM: Updated parent reference: {old_parent_id} → {new_parent_id}")
        
        await session.flush()
        
        marker = "📁" if file_record.is_folder else "📄"
        logger.info(f"  ✓ RESULT: {marker} {file_record.name} moved in database")
        logger.info(f"  ✓ RETURN: FileRecord(id={file_id[:8]}..., parent_id={new_parent_id})")
        return file_record
    
    @staticmethod
    async def rename_file(
        session: AsyncSession,
        file_id: str,
        user_id: str,
        new_name: str
    ) -> FileRecord:
        """
        Rename file/folder.
        
        Args:
            file_id: File/folder UUID
            user_id: Owner's user ID
            new_name: New name
            
        Returns:
            Updated FileRecord
        """
        logger.info(f"✏️  FLOW: rename_file() - Renaming item for user_id={user_id}")
        logger.debug(f"  ✓ INPUT: file_id={file_id[:8]}..., new_name='{new_name}'")
        
        # Get file with user validation
        logger.debug(f"  ✓ VALIDATION: Checking file ownership...")
        file_record = await FileSyncService.get_file(session, file_id, user_id)
        if not file_record:
            logger.error(f"  ✗ VALIDATION FAILED: File not found or not owned by user")
            raise ValueError(f"File {file_id} not found or not owned by user")
        
        old_name = file_record.name
        logger.debug(f"  ✓ RESULT: Found {old_name}")
        
        # Update name
        file_record.name = new_name
        logger.debug(f"  ✓ TRANSFORM: Updated name: '{old_name}' → '{new_name}'")
        
        await session.flush()
        
        logger.info(f"  ✓ RESULT: File metadata updated in database")
        marker = "📁" if file_record.is_folder else "📄"
        logger.info(f"  ✓ RETURN: {marker} FileRecord(id={file_id[:8]}..., name='{new_name}')")
        return file_record
    
    @staticmethod
    async def delete_file(session: AsyncSession, file_id: str, user_id: str) -> bool:
        """
        Delete file/folder (CASCADE for folders).
        
        Args:
            file_id: File/folder UUID
            user_id: Owner's user ID
            
        Returns:
            True if deleted
        """
        logger.info(f"🗑️  FLOW: delete_file() - Deleting item for user_id={user_id}")
        logger.debug(f"  ✓ INPUT: file_id={file_id[:8]}...")
        
        # Get file with user validation
        logger.debug(f"  ✓ VALIDATION: Checking file ownership...")
        file_record = await FileSyncService.get_file(session, file_id, user_id)
        if not file_record:
            logger.error(f"  ✗ VALIDATION FAILED: File not found or not owned by user")
            raise ValueError(f"File {file_id} not found or not owned by user")
        
        marker = "📁" if file_record.is_folder else "📄"
        logger.debug(f"  ✓ RESULT: Found {marker} {file_record.name}")
        
        # Delete record (CASCADE applies for children)
        logger.debug(f"  ✓ TRANSFORM: Cascading delete (if folder, deletes all children too)")
        await session.delete(file_record)
        await session.flush()
        
        logger.info(f"  ✓ RESULT: {marker} {file_record.name} deleted from database")
        logger.info(f"  ✓ RETURN: True (success)")
        return True
    
    @staticmethod
    async def get_version_history(
        session: AsyncSession,
        file_id: str,
        user_id: str
    ) -> list[FileVersionHistory]:
        """
        Get version history for a file (single-shard query).
        
        Args:
            file_id: File UUID
            user_id: Owner's user ID
            
        Returns:
            List of FileVersionHistory ordered by version descending
        """
        # Validate file ownership
        file_record = await FileSyncService.get_file(session, file_id, user_id)
        if not file_record:
            raise ValueError(f"File {file_id} not found or not owned by user")
        
        if file_record.is_folder:
            raise ValueError("Folders don't have version history")
        
        query = (
            select(FileVersionHistory)
            .where(FileVersionHistory.file_id == file_id)
            .where(FileVersionHistory.user_id == user_id)  # Shard key
            .order_by(FileVersionHistory.version.desc())
        )
        
        result = await session.execute(query)
        return list(result.scalars().all())
