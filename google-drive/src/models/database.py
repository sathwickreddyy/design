"""
Database models (SQLAlchemy)
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey

from ..core.database import Base


class FileRecord(Base):
    """
    File metadata record - points to CURRENT version (content stored in MinIO)
    """
    __tablename__ = "files"
    
    file_id = Column(String(255), primary_key=True, index=True)
    version = Column(Integer, nullable=False, default=1, index=True)  # Current version number
    
    # Object storage reference (current version)
    storage_key = Column(String(512), nullable=False)  # Path in MinIO
    content_hash = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String(128), default="application/octet-stream")
    
    # Timestamps
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<FileRecord(file_id='{self.file_id}', version={self.version})>"


class FileVersionHistory(Base):
    """
    Complete version history - stores ALL versions ever created
    Enables rollback, audit trail, and version browsing
    """
    __tablename__ = "file_version_history"
    
    version_id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(255), ForeignKey("files.file_id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, index=True)  # Version number
    
    # Object storage reference
    storage_key = Column(String(512), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String(128), default="application/octet-stream")
    
    # Timestamp when this version was created
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<FileVersionHistory(file_id='{self.file_id}', version={self.version}, hash={self.content_hash[:8]})>"
