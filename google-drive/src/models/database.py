"""
Database models for hierarchical file system with content-addressed storage

Uses UUID for distributed ID generation (no auto-increment hotspots).
Shard key: parent_id (co-locates folder + children on same shard).
"""
import hashlib
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


class FileRecord(Base):
    """
    Hierarchical file/folder metadata using parent_id relationships.
    
    Design:
    - Folders and files in same table (distinguished by is_folder flag)
    - Parent-child relationships via parent_id (self-referencing FK)
    - Content-addressed storage: content_hash serves as storage key
    - Bucketed storage keys computed via property (not stored)
    
    Example hierarchy:
      id=1: "My Drive" (parent_id=NULL, is_folder=TRUE)
      id=2: "Documents" (parent_id=1, is_folder=TRUE)
      id=3: "report.txt" (parent_id=2, is_folder=FALSE, content_hash=abc123...)
    """
    __tablename__ = "files"
    
    # Primary key and hierarchy (UUID for distributed generation)
    id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), 
        ForeignKey('files.id', ondelete='CASCADE'),
        nullable=True,
        index=True
    )
    
    # Multi-user sharding
    user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Owner - shard key for multi-user"
    )
    root_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="User's root folder (My Drive) for fast queries"
    )
    
    is_folder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # Version tracking (optimistic concurrency control)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # Content-addressed storage (files only, null for folders)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False
    )
    
    # Composite indexes for performance
    __table_args__ = (
        Index('idx_parent_folder', 'parent_id', 'is_folder'),  # Fast folder listing
        Index('idx_parent_name', 'parent_id', 'name'),  # Fast name lookup in folder
    )
    
    @property
    def storage_key(self) -> Optional[str]:
        """
        Generate bucketed storage key for S3/MinIO (industry best practice).
        
        Format: v1/contents/{hash[0:2]}/{hash[2:4]}/{hash}
        Example: v1/contents/a3/f7/a3f7c2e9d8b1c7f2...
        
        Benefits:
        - Distributes objects across 65,536 prefixes (256*256)
        - Avoids S3 hot partition problems
        - Follows AWS/GCS best practices
        - Better throughput at scale
        """
        if self.content_hash:
            return f"v1/contents/{self.content_hash[:2]}/{self.content_hash[2:4]}/{self.content_hash}"
        return None
    
    @property
    def shard_key(self) -> str:
        """
        Return shard key for routing queries to correct shard.
        
        Multi-user: Uses user_id to co-locate all user's files on same shard.
        Provides user isolation, quota enforcement, and single-shard queries.
        
        Returns:
            Shard key (user_id)
        """
        return self.user_id
    
    def get_shard_id(self, num_shards: int = 8) -> int:
        """
        Calculate which shard this record belongs to.
        
        Args:
            num_shards: Total number of shards (default 8)
        
        Returns:
            Shard ID (0 to num_shards-1)
        """
        hash_value = int(hashlib.md5(self.shard_key.encode()).hexdigest(), 16)
        return hash_value % num_shards
    
    def __repr__(self):
        folder_marker = "📁" if self.is_folder else "📄"
        return f"<FileRecord {folder_marker} id={self.id} name={self.name} parent_id={self.parent_id} v{self.version}>"


class FileVersionHistory(Base):
    """
    Audit trail for all file versions (hierarchical model).
    
    Tracks every version of every file for:
    - Version history viewing
    - Rollback functionality
    - Audit compliance
    
    Note: Denormalizes parent_id for sharding co-location.
    """
    __tablename__ = "file_version_history"
    
    version_id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4())
    )
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('files.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        index=True,
        comment="Denormalized for sharding"
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Denormalized - keeps history on same shard as user's files"
    )
    
    # Snapshot of file at this version
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # When this version was created
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Composite index for queries
    __table_args__ = (
        Index('idx_file_version', 'file_id', 'version'),  # Fast version lookup
    )
    
    @property
    def storage_key(self) -> str:
        """Generate bucketed storage key (same as FileRecord)"""
        return f"v1/contents/{self.content_hash[:2]}/{self.content_hash[2:4]}/{self.content_hash}"
    
    def __repr__(self):
        return f"<FileVersionHistory file_id={self.file_id} v{self.version} at {self.created_at}>"
