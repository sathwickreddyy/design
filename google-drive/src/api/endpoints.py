"""
FastAPI endpoints for hierarchical file system operations
"""
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form
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


@router.get("/", response_model=ListChildrenResponse)
async def list_root(db: Annotated[AsyncSession, Depends(get_db)]):
    """List all files/folders in root (parent_id=None)"""
    logger.info("📋 Listing root folder")
    items = await FileSyncService.list_children(db, parent_id=None)
    
    return ListChildrenResponse(
        parent_id=None,
        items=[FileMetadataResponse.model_validate(item) for item in items],
        total_count=len(items)
    )


@router.post("/folders", response_model=FileMetadataResponse, status_code=status.HTTP_201_CREATED)
async def create_folder(
    request: CreateFolderRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Create a new folder"""
    logger.info(f"📁 Creating folder: name={request.name} parent_id={request.parent_id}")
    
    try:
        folder = await FileSyncService.create_folder(
            db,
            name=request.name,
            parent_id=request.parent_id
        )
        return FileMetadataResponse.model_validate(folder)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{file_id}", response_model=FileMetadataResponse)
async def get_file_metadata(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get file/folder metadata by ID"""
    logger.info(f"📋 GET /files/{file_id}")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileMetadataResponse.model_validate(file_record)


@router.get("/{file_id}/children", response_model=ListChildrenResponse)
async def list_folder_contents(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """List contents of a folder"""
    logger.info(f"📂 Listing folder {file_id}")
    
    # Verify folder exists
    folder = await FileSyncService.get_file(db, file_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not folder.is_folder:
        raise HTTPException(status_code=400, detail="Not a folder")
    
    items = await FileSyncService.list_children(db, parent_id=file_id)
    
    return ListChildrenResponse(
        parent_id=file_id,
        items=[FileMetadataResponse.model_validate(item) for item in items],
        total_count=len(items)
    )


@router.post("/{file_id}/upload", response_model=UploadSuccessResponse, status_code=status.HTTP_201_CREATED)
async def upload_file_into_folder(
    file_id: str,
    file: Annotated[UploadFile, File(description="File to upload")],
    expected_version: Annotated[int, Form(description="Expected version (0 for new file)")],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Upload file into folder with streaming and OCC.
    
    For new files: expected_version=0
    For updates: expected_version=current_version
    """
    logger.info(f"📤 Upload into folder {file_id}: {file.filename} (expected_version={expected_version})")
    
    # Verify parent folder exists
    parent_folder = await FileSyncService.get_file(db, file_id)
    if not parent_folder:
        raise HTTPException(status_code=404, detail="Parent folder not found")
    if not parent_folder.is_folder:
        raise HTTPException(status_code=400, detail="Parent is not a folder")
    
    mime_type = file.content_type or "application/octet-stream"
    
    # Create async stream from UploadFile
    async def file_stream():
        while chunk := await file.read(8192):
            yield chunk
    
    # Check if file with same name already exists in this folder
    existing_files = await FileSyncService.list_children(db, parent_id=file_id, folders_first=False)
    existing_file = next((f for f in existing_files if f.name == file.filename and not f.is_folder), None)
    
    if not existing_file:
        # Create new file
        if expected_version != 0:
            raise HTTPException(
                status_code=400,
                detail="New file must have expected_version=0"
            )
        
        file_record = await FileSyncService.create_file_streaming(
            db,
            name=file.filename,
            parent_id=file_id,
            content_stream=file_stream(),
            mime_type=mime_type
        )
        
        return UploadSuccessResponse(
            status="created",
            file=FileMetadataResponse.model_validate(file_record)
        )
    
    # Update existing file with OCC
    success, file_or_conflict = await FileSyncService.update_file_optimistic_streaming(
        db,
        file_id=existing_file.id,
        content_stream=file_stream(),
        expected_version=expected_version
    )
    
    if not success:
        # Version conflict
        current_file = file_or_conflict
        conflict_response = ConflictResponse(
            message=f"Version conflict: expected {expected_version}, server has {current_file.version}",
            current_version=current_file.version,
            expected_version=expected_version
        )
        
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=conflict_response.model_dump()
        )
    
    # Success
    return UploadSuccessResponse(
        status="updated",
        file=FileMetadataResponse.model_validate(file_or_conflict)
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Download file content with streaming.
    
    Features:
    - Streams from MinIO (constant memory)
    - Content-Length for progress tracking
    - ETag for caching
    - Bucketed storage keys
    """
    logger.info(f"📥 Download file {file_id}")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    if file_record.is_folder:
        raise HTTPException(status_code=400, detail="Cannot download folder")
    
    logger.info(f"✅ Streaming {file_record.name} v{file_record.version} ({file_record.size_bytes} bytes)")
    
    # Streaming generator
    async def stream_from_minio():
        """
        Stream file chunks from MinIO with constant memory usage via thread pool.
        
        Key pattern (response types):
        1. await loop.run_in_executor(..., get_object, ...) → returns HTTPResponse stream object (~0 bytes)
           This is just metadata, not the actual file data
        2. await loop.run_in_executor(..., response.read, 8192) → returns bytes chunk (~8192 bytes)
           This is the actual file data for this iteration
        
        Why await each read()? 
        Each response.read() is a blocking call. By submitting it to executor thread pool,
        the event loop stays FREE and can handle other concurrent requests (other downloads, DB queries, etc)
        Without this, the event loop would freeze while waiting for each read() to complete.
        """
        import asyncio
        response = None
        try:
            # Get stream object from MinIO (returns HTTPResponse, not file data)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                storage_service.client.get_object,
                storage_service.bucket,
                file_record.storage_key
            )
            
            # Yield chunks (8KB per iteration) - EACH read in executor to keep event loop free
            while True:
                chunk = await loop.run_in_executor(None, response.read, 8192)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            logger.error(f"❌ Streaming error for file {file_id}: {e}")
            raise
        finally:
            if response:
                response.close()
    
    from urllib.parse import quote
    safe_filename = quote(file_record.name, safe='')
    
    return StreamingResponse(
        stream_from_minio(),
        media_type=file_record.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(file_record.size_bytes),
            "X-File-Version": str(file_record.version),
            "ETag": f'"{file_record.content_hash}"',
            "Cache-Control": "public, max-age=31536000",
        }
    )


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Delete file/folder (removes metadata, content stays for deduplication)"""
    logger.info(f"🗑️  DELETE /files/{file_id}")
    
    success = await FileSyncService.delete_file(db, file_id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {"status": "deleted", "file_id": file_id}


@router.patch("/{file_id}/move")
async def move_file(
    file_id: str,
    request: MoveFileRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Move file/folder to different parent"""
    logger.info(f"🔄 Move file {file_id} to parent {request.new_parent_id}")
    
    try:
        file_record = await FileSyncService.move_file(
            db,
            file_id=file_id,
            new_parent_id=request.new_parent_id
        )
        return FileMetadataResponse.model_validate(file_record)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{file_id}/rename")
async def rename_file(
    file_id: str,
    request: RenameFileRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Rename file/folder"""
    logger.info(f"✏️  Rename file {file_id} to {request.new_name}")
    
    try:
        file_record = await FileSyncService.rename_file(
            db,
            file_id=file_id,
            new_name=request.new_name
        )
        return FileMetadataResponse.model_validate(file_record)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{file_id}/history", response_model=list[VersionHistoryItem])
async def get_version_history(
    file_id: str,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Get complete version history for a file"""
    logger.info(f"📚 GET /files/{file_id}/history")
    
    # Verify file exists
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    if file_record.is_folder:
        raise HTTPException(status_code=400, detail="Folders don't have version history")
    
    history = await FileSyncService.get_version_history(db, file_id)
    
    return [VersionHistoryItem.model_validate(h) for h in history]


@router.get("/{file_id}/version/{version_number}")
async def download_file_version(
    file_id: str,
    version_number: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Download specific version of a file"""
    logger.info(f"📥 Download file {file_id} version {version_number}")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    if file_record.is_folder:
        raise HTTPException(status_code=400, detail="Cannot download folder")
    
    # Check if current version
    if file_record.version == version_number:
        storage_key = file_record.storage_key
        content_hash = file_record.content_hash
        mime_type = file_record.mime_type
        size_bytes = file_record.size_bytes
        name = file_record.name
    else:
        # Look in history
        from sqlalchemy import select
        from ..models import FileVersionHistory
        
        result = await db.execute(
            select(FileVersionHistory)
            .where(
                FileVersionHistory.file_id == file_id,
                FileVersionHistory.version == version_number
            )
        )
        history_entry = result.scalar_one_or_none()
        
        if not history_entry:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
        
        storage_key = history_entry.storage_key
        content_hash = history_entry.content_hash
        mime_type = history_entry.mime_type
        size_bytes = history_entry.size_bytes
        name = history_entry.name
    
    # Streaming download
    async def stream_from_minio():
        import asyncio
        response = None
        try:
            loop = asyncio.get_event_loop()
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
        finally:
            if response:
                response.close()
    
    from urllib.parse import quote
    safe_filename = quote(f"{name}_v{version_number}", safe='')
    
    return StreamingResponse(
        stream_from_minio(),
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(size_bytes),
            "X-File-Version": str(version_number),
            "ETag": f'"{content_hash}"',
            "Cache-Control": "public, max-age=31536000",
        }
    )
