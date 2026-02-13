"""
Pydantic schemas for API request/response validation (multi-user)
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class FileMetadataResponse(BaseModel):
    """Response schema for file/folder metadata"""
    # Core identity
    id: str  # UUID: Distributed ID generation (no sequence hotspots, globally unique across shards)
    name: str  # Original filename
    
    # Hierarchy
    parent_id: Optional[str]  # Parent folder ID (None = root folder)
    
    # Sharding & Multi-user isolation
    user_id: str  # ✅ DENORMALIZED: Shard key for ownership validation. Included here to:
                 #   1. Validate in API layer (fail fast before DB)
                 #   2. Enable consistent hashing (route to correct shard)
                 #   3. Prevent cross-user data leaks
    root_id: str  # ✅ DENORMALIZED: User's "My Drive" folder (avoids backtracking parent chain).
                 #   Without this: every path query needs parent-child traversal to find root
                 #   With this: O(1) lookup of user's storage quota, trash folder, shared root
    
    # File properties
    is_folder: bool  # Type discriminator (folder vs file)
    version: int  # OCC: Current version for conflict detection
    content_hash: Optional[str]  # SHA-256 hash (deduplication, integrity verification)
    size_bytes: Optional[int]  # File size (quota accounting, UI display)
    mime_type: Optional[str]  # Content-type (client rendering, preview generation)
    
    # Timestamps
    created_at: datetime  # Immutable creation time
    updated_at: datetime  # Latest modification (sorting, freshness checks)
    
    class Config:
        from_attributes = True


class ListChildrenResponse(BaseModel):
    """Response for listing folder contents"""
    parent_id: Optional[str]  # Echoed back (client state tracking)
    user_id: str  # ✅ DENORMALIZED: Proves query was restricted to single user (security proof)
    items: list[FileMetadataResponse]  # Children of parent_id
    total_count: int  # Total without pagination (UI: "Showing 1-50 of 1,234")


class CreateFolderRequest(BaseModel):
    """Request to create a new folder"""
    name: str = Field(..., min_length=1, max_length=255)  # Folder name
    parent_id: Optional[str] = None  # None = create in root. Validated for ownership in service layer
    user_id: str = Field(..., description="Owner of the folder")  # ✅ REQUIRED: Ownership validation + shard routing


class UploadFileRequest(BaseModel):
    """Metadata for file upload (multipart form data)"""
    parent_id: Optional[str] = None  # Destination folder. Validated for ownership
    user_id: str = Field(..., description="Owner of the file")  # ✅ REQUIRED: Validates parent ownership + shard routing
    expected_version: Optional[int] = Field(None, description="For updates only (OCC)")  # Optimistic concurrency control


class UpdateFileRequest(BaseModel):
    """Request to update file content"""
    expected_version: int = Field(..., description="Current version for OCC")  # Prevents lost updates when multiple clients edit simultaneously
    user_id: str  # ✅ REQUIRED: Ownership check (attacker can't modify other user's files)


class MoveFileRequest(BaseModel):
    """Request to move file/folder to different parent"""
    new_parent_id: Optional[str] = None  # Destination folder. Must be owned by same user
    user_id: str = Field(..., description="Must be owner")  # ✅ REQUIRED: Validates both source & destination are same user


class RenameFileRequest(BaseModel):
    """Request to rename file/folder"""
    new_name: str = Field(..., min_length=1, max_length=255)  # New name
    user_id: str  # ✅ REQUIRED: Ownership validation


class VersionHistoryItem(BaseModel):
    """Single version in history"""
    version_id: str  # Unique ID for this version (UUID)
    version: int  # Version number (1, 2, 3, ...). Used for OCC
    content_hash: str  # SHA-256: Deduplication across versions (if hash matches, skip re-upload)
    size_bytes: int  # Size of this version
    created_at: datetime  # When this version was created
    # ✅ DENORMALIZED: user_id is in database but NOT in response because:
    #    1. Client already knows user_id (it made the request)
    #    2. Reduces response size (bandwidth optimization for version lists)
    #    3. Not needed for client logic (user can only see their own history)
    
    class Config:
        from_attributes = True


class ConflictResponse(BaseModel):
    """Response when version conflict occurs"""
    error: str = "Version conflict"  # Error code
    current_version: int  # Current version in DB (helps client retry with correct version)
    expected_version: int  # What client thought was current (shows conflict)
    file_id: str  # Which file had conflict (for retry logic)


class UploadSuccessResponse(BaseModel):
    """Response after successful file upload"""
    id: str  # File ID (for future operations)
    name: str  # Confirmed name
    user_id: str  # ✅ ECHOED: Confirms ownership in response
    version: int  # Version 1 (new files start at v1)
    content_hash: str  # SHA-256: Client stores for deduplication in future uploads
    size_bytes: int  # Confirmed size after upload
    message: str = "File uploaded successfully"  # Status message
