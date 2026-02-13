"""
FastAPI endpoints for multi-user hierarchical file system
"""
import asyncio
import logging
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..schemas import (
    FileMetadataResponse,
    ListChildrenResponse,
    CreateFolderRequest,
    UpdateFileRequest,
    MoveFileRequest,
    RenameFileRequest,
    VersionHistoryItem,
    ConflictResponse,
    UploadSuccessResponse
)
from ..services import FileSyncService, storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

# TODO: Replace with real auth - for now use header
def get_current_user(x_user_id: str = Header(..., description="User ID (temporary auth)")) -> str:
    """Get current user ID from header (placeholder for real auth)"""
    return x_user_id


@router.get("/", response_model=ListChildrenResponse)
async def list_root(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """List all files/folders in user's root"""
    logger.info(f"📋 Listing root folder for user_id={user_id}")
    items = await FileSyncService.list_children(db, user_id=user_id, parent_id=None)
    
    return ListChildrenResponse(
        parent_id=None,
        user_id=user_id,
        items=[FileMetadataResponse.model_validate(item) for item in items],
        total_count=len(items)
    )


@router.post("/folders", response_model=FileMetadataResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    request: CreateFolderRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Create a new folder"""
    logger.info(f"📁 Creating folder: name={request.name} parent_id={request.parent_id} user_id={user_id}")
    
    try:
        folder = await FileSyncService.create_folder(
            db,
            name=request.name,
            user_id=user_id,
            parent_id=request.parent_id
        )
        await db.commit()
        return FileMetadataResponse.model_validate(folder)
    
    except ValueError as e:
        logger.error(f"❌ Folder creation failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{file_id}", response_model=FileMetadataResponse)
async def get_file_metadata(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Get file/folder metadata by ID"""
    logger.info(f"📄 Getting metadata: file_id={file_id} user_id={user_id}")
    
    file_record = await FileSyncService.get_file(db, file_id, user_id)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {file_id} not found"
        )
    
    return FileMetadataResponse.model_validate(file_record)


@router.get("/{file_id}/children", response_model=ListChildrenResponse)
async def list_folder_contents(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """List contents of a folder"""
    logger.info(f"📂 Listing folder: file_id={file_id} user_id={user_id}")
    
    # Verify it's a folder
    folder = await FileSyncService.get_file(db, file_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Folder {file_id} not found"
        )
    
    if not folder.is_folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not a folder"
        )
    
    items = await FileSyncService.list_children(db, user_id=user_id, parent_id=file_id)
    
    return ListChildrenResponse(
        parent_id=file_id,
        user_id=user_id,
        items=[FileMetadataResponse.model_validate(item) for item in items],
        total_count=len(items)
    )


@router.post("/{folder_id}/upload", response_model=UploadSuccessResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    folder_id: str,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)],
    expected_version: Annotated[Optional[int], Form()] = None
):
    """
    Upload a new file or update existing file with OCC.
    
    - If expected_version is provided, updates existing file
    - Otherwise, creates new file
    """
    logger.info(
        f"📤 Upload: folder_id={folder_id} file={file.filename} "
        f"user_id={user_id} expected_version={expected_version}"
    )
    
    # Streaming upload
    async def content_stream():
        while chunk := await file.read(8192):  # 8KB chunks
            yield chunk
    
    try:
        if expected_version is not None:
            # Update existing file
            # Extract file_id from filename or require separate endpoint
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use PATCH /files/{file_id}/content for updates"
            )
        else:
            # Create new file
            file_record = await FileSyncService.create_file_streaming(
                db,
                name=file.filename,
                user_id=user_id,
                content_stream=content_stream(),
                parent_id=folder_id,
                mime_type=file.content_type or "application/octet-stream"
            )
            await db.commit()
            
            return UploadSuccessResponse(
                id=file_record.id,
                name=file_record.name,
                user_id=file_record.user_id,
                version=file_record.version,
                content_hash=file_record.content_hash,
                size_bytes=file_record.size_bytes,
                message="File uploaded successfully"
            )
    
    except ValueError as e:
        logger.error(f"❌ Upload failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{file_id}/content", response_model=FileMetadataResponse)
async def update_file_content(
    file_id: str,
    file: Annotated[UploadFile, File(...)],
    expected_version: Annotated[int, Form(...)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Update file content with optimistic concurrency control"""
    logger.info(f"🔄 Update: file_id={file_id} user_id={user_id} expected_v={expected_version}")
    
    async def content_stream():
        while chunk := await file.read(8192):
            yield chunk
    
    try:
        file_record = await FileSyncService.update_file_optimistic_streaming(
            db,
            file_id=file_id,
            user_id=user_id,
            content_stream=content_stream(),
            expected_version=expected_version,
            mime_type=file.content_type
        )
        await db.commit()
        return FileMetadataResponse.model_validate(file_record)
    
    except ValueError as e:
        if "Version conflict" in str(e):
            # Get current version for client
            current_file = await FileSyncService.get_file(db, file_id, user_id)
            current_version = current_file.version if current_file else 0
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ConflictResponse(
                    error="Version conflict",
                    current_version=current_version,
                    expected_version=expected_version,
                    file_id=file_id
                ).dict()
            )
        else:
            logger.error(f"❌ Update failed: {e}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Download file content (streaming)"""
    logger.info(f"📥 Download: file_id={file_id} user_id={user_id}")
    
    file_record = await FileSyncService.get_file(db, file_id, user_id)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File {file_id} not found"
        )
    
    if file_record.is_folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot download folder"
        )
    
    storage_key = file_record.storage_key
    
    # Get event loop for async executor
    loop = asyncio.get_event_loop()
    
    # Streaming generator
    async def stream_file():
        try:
            # Get MinIO response object (sync)
            response = await loop.run_in_executor(
                None,
                storage_service.client.get_object,
                storage_service.bucket,
                storage_key
            )
            
            # Stream chunks (8KB)
            while True:
                chunk = await loop.run_in_executor(None, response.read, 8192)
                if not chunk:
                    break
                yield chunk
            
            # Close response
            await loop.run_in_executor(None, response.close)
            await loop.run_in_executor(None, response.release_conn)
        
        except Exception as e:
            logger.error(f"❌ Download stream error: {e}")
            raise
    
    headers = {
        "Content-Length": str(file_record.size_bytes),
        "Content-Type": file_record.mime_type or "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{quote(file_record.name)}"',
        "ETag": file_record.content_hash,
        "Cache-Control": "public, max-age=31536000, immutable"
    }
    
    return StreamingResponse(
        stream_file(),
        headers=headers,
        media_type=file_record.mime_type or "application/octet-stream"
    )


@router.patch("/{file_id}/move", response_model=FileMetadataResponse)
async def move_file(
    file_id: str,
    request: MoveFileRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Move file/folder to different parent"""
    logger.info(f"📦 Move: file_id={file_id} user_id={user_id} → parent={request.new_parent_id}")
    
    try:
        file_record = await FileSyncService.move_file(
            db,
            file_id=file_id,
            user_id=user_id,
            new_parent_id=request.new_parent_id
        )
        await db.commit()
        return FileMetadataResponse.model_validate(file_record)
    
    except ValueError as e:
        logger.error(f"❌ Move failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch("/{file_id}/rename", response_model=FileMetadataResponse)
async def rename_file(
    file_id: str,
    request: RenameFileRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Rename file/folder"""
    logger.info(f"✏️  Rename: file_id={file_id} user_id={user_id} → {request.new_name}")
    
    try:
        file_record = await FileSyncService.rename_file(
            db,
            file_id=file_id,
            user_id=user_id,
            new_name=request.new_name
        )
        await db.commit()
        return FileMetadataResponse.model_validate(file_record)
    
    except ValueError as e:
        logger.error(f"❌ Rename failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Delete file/folder (CASCADE for folders)"""
    logger.info(f"🗑️  Delete: file_id={file_id} user_id={user_id}")
    
    try:
        await FileSyncService.delete_file(db, file_id=file_id, user_id=user_id)
        await db.commit()
        return None
    
    except ValueError as e:
        logger.error(f"❌ Delete failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{file_id}/history", response_model=list[VersionHistoryItem])
async def get_version_history(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Get version history for a file"""
    logger.info(f"📜 Version history: file_id={file_id} user_id={user_id}")
    
    try:
        history = await FileSyncService.get_version_history(db, file_id=file_id, user_id=user_id)
        return [VersionHistoryItem.model_validate(item) for item in history]
    
    except ValueError as e:
        logger.error(f"❌ History failed: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{file_id}/version/{version_number}")
async def download_version(
    file_id: str,
    version_number: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)]
):
    """Download specific version of a file"""
    logger.info(f"📥 Download version: file_id={file_id} v={version_number} user_id={user_id}")
    
    # Get version from history
    history = await FileSyncService.get_version_history(db, file_id=file_id, user_id=user_id)
    version_record = next((v for v in history if v.version == version_number), None)
    
    if not version_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found"
        )
    
    storage_key = version_record.storage_key
    loop = asyncio.get_event_loop()
    
    async def stream_file():
        try:
            response = await loop.run_in_executor(
                None,
                storage_service.client.get_object,
                storage_service.bucket,
                storage_key
            )
            
            while True:
                chunk = await loop.run_in_executor(None, response.read, 8192)
                if not chunk:
                    break
                yield chunk
            
            await loop.run_in_executor(None, response.close)
            await loop.run_in_executor(None, response.release_conn)
        
        except Exception as e:
            logger.error(f"❌ Download version error: {e}")
            raise
    
    headers = {
        "Content-Length": str(version_record.size_bytes),
        "Content-Type": version_record.mime_type or "application/octet-stream",
        "Content-Disposition": f'attachment; filename="{quote(version_record.name)}-v{version_number}"',
        "ETag": version_record.content_hash
    }
    
    return StreamingResponse(
        stream_file(),
        headers=headers,
        media_type=version_record.mime_type or "application/octet-stream"
    )
