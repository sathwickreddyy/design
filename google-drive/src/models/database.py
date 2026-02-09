"""
Database models for hierarchical file system with content-addressed storage
"""
from datetime import datetime
from typing import Optional

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
    
    # Primary key and hierarchy
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, 
        ForeignKey('files.id', ondelete='CASCADE'),
        nullable=True,
        index=True
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
    """
    __tablename__ = "file_version_history"
    
    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('files.id', ondelete='CASCADE'),
        nullable=False,
        index=True
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
