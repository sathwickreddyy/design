"""
Pydantic schemas for API request/response models
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FileMetadataResponse(BaseModel):
    """File/folder metadata response"""
    id: str
    name: str
    parent_id: Optional[str]
    is_folder: bool
    version: int
    content_hash: Optional[str] = None
    size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ListChildrenResponse(BaseModel):
    """Response for listing folder contents"""
    parent_id: Optional[str]
    items: list[FileMetadataResponse]
    total_count: int


class CreateFolderRequest(BaseModel):
    """Request to create a folder"""
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[str] = None


class UploadFileRequest(BaseModel):
    """Metadata for file upload (form data)"""
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[str] = None


class UpdateFileRequest(BaseModel):
    """Request to update file"""
    expected_version: int = Field(..., ge=1)


class MoveFileRequest(BaseModel):
    """Request to move file/folder"""
    new_parent_id: Optional[str] = None


class RenameFileRequest(BaseModel):
    """Request to rename file/folder"""
    new_name: str = Field(..., min_length=1, max_length=255)


class VersionHistoryItem(BaseModel):
    """Single version history entry"""
    version: int
    content_hash: str
    size_bytes: int
    mime_type: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class ConflictResponse(BaseModel):
    """Response when version conflict occurs"""
    error: str = "version_conflict"
    message: str
    current_version: int
    expected_version: int


class UploadSuccessResponse(BaseModel):
    """Response after successful file upload/update"""
    status: str  # "created" or "updated"
    file: FileMetadataResponse
