"""Database models for upload sessions."""
from sqlalchemy import Column, String, BigInteger, Integer, ARRAY, TIMESTAMP, JSON
from sqlalchemy.sql import func
from database import Base


class UploadSession(Base):
    """Upload session metadata stored in PostgreSQL."""
    
    __tablename__ = "upload_sessions"
    
    session_id = Column(String(64), primary_key=True, index=True)
    filename = Column(String(512), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    total_parts = Column(Integer, nullable=False)
    completed_parts = Column(ARRAY(Integer), default=[])
    
    # Checksum fields
    file_hash = Column(String(64), nullable=True)  # SHA256 of full file (hex string)
    hash_algorithm = Column(String(20), default="SHA256")
    part_hashes = Column(JSON, default={})  # {"1": "md5_hex", "2": "md5_hex", ...}
    
    status = Column(String(20), default="in_progress", index=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    completed_at = Column(TIMESTAMP, nullable=True)
    
    def __repr__(self):
        return f"<UploadSession(session_id={self.session_id}, filename={self.filename}, status={self.status})>"
