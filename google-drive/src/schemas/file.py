"""
Pydantic schemas for API request/response validation
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FileUploadRequest(BaseModel):
    """Request to upload file content (for demo/text files)"""
    content: str = Field(..., description="File content (base64 or text)")
    expected_version: int = Field(..., description="Expected current version for optimistic locking")
    content_hash: Optional[str] = Field(None, description="SHA256 hash of content for integrity check")


class FileMetadataResponse(BaseModel):
    """File metadata without content"""
    file_id: str
    version: int
    content_hash: str
    size_bytes: int
    mime_type: str
    storage_key: str
    updated_at: datetime


class FileResponse(BaseModel):
    """File with content"""
    file_id: str
    content: str
    version: int
    content_hash: str
    size_bytes: int
    updated_at: datetime


class ConflictResponse(BaseModel):
    """Conflict error response"""
    error: str = "CONFLICT"
    message: str
    current_version: int
    server_content: str
    server_hash: str


class UploadSuccessResponse(BaseModel):
    """Successful upload response"""
    status: str
    file_id: str
    version: int
    content_hash: str
    storage_key: str
    size_bytes: int
