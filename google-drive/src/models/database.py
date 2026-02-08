"""
Database models (SQLAlchemy)
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, BigInteger, DateTime

from ..core.database import Base


class FileRecord(Base):
    """
    File metadata record (content stored in MinIO)
    """
    __tablename__ = "files"
    
    file_id = Column(String(255), primary_key=True, index=True)
    version = Column(Integer, nullable=False, default=1, index=True)
    
    # Object storage reference
    storage_key = Column(String(512), nullable=False)  # Path in MinIO
    content_hash = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String(128), default="application/octet-stream")
    
    # Timestamps
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<FileRecord(file_id='{self.file_id}', version={self.version})>"
