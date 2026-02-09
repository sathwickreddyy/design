"""
FastAPI endpoints for file sync operations
"""
import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File, Form, Path
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from ..core.database import get_db
from ..schemas import (
    FileUploadRequest,
    FileMetadataResponse,
    FileResponse,
    ConflictResponse,
    UploadSuccessResponse
)
from ..services import FileSyncService, storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/", response_model=list[dict])
async def list_files(db: Annotated[AsyncSession, Depends(get_db)]):
    """List all files in the system (metadata only)"""
    logger.info("📋 Listing all files")
    files = await FileSyncService.list_all_files(db)
    return [
        {
            "file_id": f.file_id,
            "version": f.version,
            "content_hash": f.content_hash,
            "size_bytes": f.size_bytes,
            "updated_at": f.updated_at.isoformat()
        }
        for f in files
    ]


@router.get("/{file_id:path}/metadata", response_model=FileMetadataResponse)
async def get_file_metadata(file_id: Annotated[str, Path()], db: Annotated[AsyncSession, Depends(get_db)]):
    """Get file metadata without downloading content"""
    logger.info(f"📋 GET /files/{file_id}/metadata")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileMetadataResponse(
        file_id=file_record.file_id,
        version=file_record.version,
        content_hash=file_record.content_hash,
        size_bytes=file_record.size_bytes,
        mime_type=file_record.mime_type,
        storage_key=file_record.storage_key,
        updated_at=file_record.updated_at
    )


@router.get("/{file_id:path}/download")
async def download_file(file_id: Annotated[str, Path()], db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Download file content (binary streaming) - supports file_ids with slashes like 'videos/file.mp4'
    
    Features:
    - Streams content directly from MinIO (constant memory, works for large files)
    - Includes Content-Length for progress tracking
    - Uses ETag for caching/conditional requests
    - Sanitizes filename for safe HTTP headers
    """
    logger.info(f"📥 GET /files/{file_id}/download")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    logger.info(f"✅ Streaming {file_id} v{file_record.version} ({file_record.size_bytes} bytes)")
    
    # Create async generator that streams from MinIO
    async def stream_from_minio():
        """Stream file chunks from MinIO (constant memory usage via thread pool)"""
        import asyncio
        response = None
        try:
            # Run sync MinIO call in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                storage_service.client.get_object,
                storage_service.bucket,
                file_record.storage_key
            )
            
            # Yield chunks (8KB per iteration)
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            logger.error(f"❌ Streaming error for {file_id}: {e}")
            raise
        finally:
            if response:
                response.close()
    
    # Sanitize filename for HTTP header
    safe_filename = quote(file_id.split("/")[-1], safe='')
    
    return StreamingResponse(
        stream_from_minio(),
        media_type=file_record.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(file_record.size_bytes),  # For progress tracking
            "X-File-Version": str(file_record.version),
            "ETag": f'"{file_record.content_hash}"',  # For caching
            "Cache-Control": "public, max-age=31536000",  # Cache 1 year (content is immutable)
        }
    )


@router.get("/{file_id:path}", response_model=FileResponse)
async def get_file_text(file_id: Annotated[str, Path()], db: Annotated[AsyncSession, Depends(get_db)]):
    """Get file content as text (for demo/text files)"""
    logger.info(f"📥 GET /files/{file_id}")
    
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Download content
    try:
        content_bytes = await FileSyncService.get_file_content(file_record)
    except Exception as e:
        logger.error(f"❌ Failed to download {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve file content")
    
    return FileResponse(
        file_id=file_record.file_id,
        content=content_bytes.decode('utf-8'),
        version=file_record.version,
        content_hash=file_record.content_hash,
        size_bytes=file_record.size_bytes,
        updated_at=file_record.updated_at
    )


@router.post("/upload", response_model=UploadSuccessResponse, status_code=status.HTTP_201_CREATED)
async def upload_file_multipart(
    file: Annotated[UploadFile, File(description="File to upload")],
    file_id: Annotated[str, Form(description="Unique file identifier (e.g., 'docs/report.txt')")],
    expected_version: Annotated[int, Form(description="Expected current version (0 for new file)")],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Upload file via multipart/form-data with STREAMING (production-grade!)
    
    This endpoint:
    1. Streams the file from UploadFile (constant memory, works for large files)
    2. Computes hash while streaming (single pass)
    3. Stores in MinIO content-addressed storage
    4. Updates metadata in PostgreSQL with optimistic locking
    
    For new files: expected_version=0
    For updates: provide the current version you have
    """
    logger.info(f"📤 POST /files/upload STREAMING (file_id={file_id}, expected_version={expected_version})")
    
    mime_type = file.content_type or "application/octet-stream"
    
    # Create async iterator from UploadFile
    async def file_stream():
        """Stream file in chunks"""
        while chunk := await file.read(8192):  # 8KB chunks
            yield chunk
    
    # Check if file exists
    existing_file = await FileSyncService.get_file(db, file_id)
    
    if not existing_file:
        # Create new file with streaming
        if expected_version != 0:
            raise HTTPException(
                status_code=400,
                detail="New file must have expected_version=0"
            )
        
        file_record, storage_key = await FileSyncService.create_file_streaming(
            db, file_id, file_stream(), mime_type
        )
        
        return UploadSuccessResponse(
            status="created",
            file_id=file_record.file_id,
            version=file_record.version,
            content_hash=file_record.content_hash,
            storage_key=storage_key,
            size_bytes=file_record.size_bytes
        )
    
    # Update existing file with optimistic locking + streaming
    success, file_or_conflict, storage_key = await FileSyncService.update_file_optimistic_streaming(
        db, file_id, file_stream(), expected_version
    )
    
    if not success:
        # CONFLICT! Return current version
        current_file = file_or_conflict
        
        # Download current content for conflict response
        try:
            current_content = await FileSyncService.get_file_content(current_file)
            current_content_str = current_content.decode('utf-8', errors='replace')
        except Exception as e:
            logger.error(f"❌ Failed to get conflict content: {e}")
            current_content_str = "<binary content>"
        
        conflict_response = ConflictResponse(
            message=f"Version conflict: expected {expected_version}, server has {current_file.version}",
            current_version=current_file.version,
            server_content=current_content_str[:1000],  # Limit size
            server_hash=current_file.content_hash
        )
        
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=conflict_response.model_dump()
        )
    
    # Success!
    updated_file = file_or_conflict
    return UploadSuccessResponse(
        status="updated",
        file_id=updated_file.file_id,
        version=updated_file.version,
        content_hash=updated_file.content_hash,
        storage_key=storage_key,
        size_bytes=updated_file.size_bytes
    )


@router.post("/{file_id:path}", response_model=UploadSuccessResponse)
async def upload_file_text(
    file_id: Annotated[str, Path()],
    request: FileUploadRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Upload file as text/JSON (Legacy endpoint for demos)
    
    Use /files/upload for real file uploads instead.
    This endpoint is kept for backward compatibility with demo scripts.
    """
    logger.info(f"📤 POST /files/{file_id} (expected_version={request.expected_version})")
    
    content_bytes = request.content.encode('utf-8')
    
    # Check if file exists
    existing_file = await FileSyncService.get_file(db, file_id)
    
    if not existing_file:
        if request.expected_version != 0:
            raise HTTPException(
                status_code=400,
                detail="New file must have expected_version=0"
            )
        
        file_record, storage_key = await FileSyncService.create_file(
            db, file_id, content_bytes, "text/plain"
        )
        
        return UploadSuccessResponse(
            status="created",
            file_id=file_record.file_id,
            version=file_record.version,
            content_hash=file_record.content_hash,
            storage_key=storage_key,
            size_bytes=file_record.size_bytes
        )
    
    # Update with optimistic locking
    try:
        success, file_or_conflict, storage_key = await FileSyncService.update_file_optimistic(
            db, file_id, content_bytes, request.expected_version, request.content_hash
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": "INTEGRITY_ERROR", "message": str(e)})
    
    if not success:
        # CONFLICT!
        current_file = file_or_conflict
        
        try:
            current_content = await FileSyncService.get_file_content(current_file)
            current_content_str = current_content.decode('utf-8')
        except Exception:
            current_content_str = "<content unavailable>"
        
        conflict_response = ConflictResponse(
            message=f"Version conflict: expected {request.expected_version}, server has {current_file.version}",
            current_version=current_file.version,
            server_content=current_content_str,
            server_hash=current_file.content_hash
        )
        
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=conflict_response.model_dump()
        )
    
    # Success!
    updated_file = file_or_conflict
    return UploadSuccessResponse(
        status="updated",
        file_id=updated_file.file_id,
        version=updated_file.version,
        content_hash=updated_file.content_hash,
        storage_key=storage_key,
        size_bytes=updated_file.size_bytes
    )


@router.delete("/{file_id:path}")
async def delete_file(file_id: Annotated[str, Path()], db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Delete file metadata
    
    Note: With content-addressed storage, we only delete metadata.
    The actual content remains in storage as other files may reference it.
    In production, run garbage collection periodically to clean up orphaned content.
    """
    logger.info(f"🗑️ DELETE /files/{file_id}")
    
    success = await FileSyncService.delete_file(db, file_id)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {"status": "deleted", "file_id": file_id}


@router.get("/{file_id:path}/history", response_model=list[dict])
async def get_file_version_history(file_id: Annotated[str, Path()], db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Get complete version history for a file
    
    Returns all versions ever created, ordered by version number.
    Enables viewing past versions and understanding change history.
    """
    logger.info(f"📚 GET /files/{file_id}/history")
    
    # Verify file exists
    file_record = await FileSyncService.get_file(db, file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get all historical versions
    from sqlalchemy import select
    from src.models import FileVersionHistory
    
    result = await db.execute(
        select(FileVersionHistory)
        .where(FileVersionHistory.file_id == file_id)
        .order_by(FileVersionHistory.version.asc())
    )
    
    history = result.scalars().all()
    
    return [
        {
            "version": h.version,
            "content_hash": h.content_hash,
            "size_bytes": h.size_bytes,
            "mime_type": h.mime_type,
            "created_at": h.created_at.isoformat()
        }
        for h in history
    ]


@router.get("/{file_id:path}/version/{version_number}")
async def get_file_version_content(
    file_id: Annotated[str, Path()],
    version_number: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Download a specific historical version of a file
    
    Features:
    - Stream directly from MinIO (constant memory)
    - Includes Content-Length and ETag headers
    - Safe filename handling
    """
    logger.info(f"📥 GET /files/{file_id}/version/{version_number}")
    
    from sqlalchemy import select
    from src.models import FileVersionHistory
    
    # Check if it's the current version
    current_file = await FileSyncService.get_file(db, file_id)
    if not current_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    if current_file.version == version_number:
        # Return current version
        storage_key = current_file.storage_key
        content_hash = current_file.content_hash
        mime_type = current_file.mime_type
        size_bytes = current_file.size_bytes
    else:
        # Look in history
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
    
    logger.info(f"✅ Streaming {file_id} v{version_number} ({size_bytes} bytes)")
    
    # Create async generator that streams from MinIO
    async def stream_from_minio():
        """Stream file chunks from MinIO (constant memory usage via thread pool)"""
        import asyncio
        response = None
        try:
            # Run sync MinIO call in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                storage_service.client.get_object,
                storage_service.bucket,
                storage_key
            )
            
            # Yield chunks (8KB per iteration)
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                yield chunk
        except Exception as e:
            logger.error(f"❌ Streaming error for {file_id} v{version_number}: {e}")
            raise
        finally:
            if response:
                response.close()
    
    # Sanitize filename
    safe_filename = quote(file_id.split("/")[-1], safe='')
    
    return StreamingResponse(
        stream_from_minio(),
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}_v{version_number}"',
            "Content-Length": str(size_bytes),
            "X-File-Version": str(version_number),
            "ETag": f'"{content_hash}"',
            "Cache-Control": "public, max-age=31536000",
        }
    )


@router.post("/{file_id:path}/rollback/{version_number}")
async def rollback_to_version(
    file_id: Annotated[str, Path()],
    version_number: int,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Rollback file to a specific historical version
    
    This creates a new version (increment) that matches the content of the specified version.
    """
    logger.info(f"🔄 POST /files/{file_id}/rollback/{version_number}")
    
    from sqlalchemy import select
    from src.models import FileVersionHistory
    
    current_file = await FileSyncService.get_file(db, file_id)
    if not current_file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Find the version to rollback to
    if current_file.version == version_number:
        raise HTTPException(
            status_code=400,
            detail=f"Already at version {version_number}"
        )
    
    if current_file.version > version_number:
        # It's in history
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
        
        rollback_storage_key = history_entry.storage_key
        rollback_hash = history_entry.content_hash
        rollback_size = history_entry.size_bytes
        rollback_mime = history_entry.mime_type
    else:
        # Future version doesn't exist
        raise HTTPException(status_code=404, detail=f"Version {version_number} not found (beyond current)")
    
    # Download the old version content
    try:
        old_content = storage_service.download(rollback_storage_key)
    except Exception as e:
        logger.error(f"❌ Failed to rollback {file_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve version content")
    
    # Create new version from old content (as bytes)
    success, updated_file, storage_key = await FileSyncService.update_file_optimistic(
        db,
        file_id=file_id,
        content=old_content,
        expected_version=current_file.version,
        content_hash_provided=None
    )
    
    if not success:
        raise HTTPException(status_code=409, detail="Version conflict during rollback")
    
    logger.info(f"✅ Rolled back {file_id} to v{version_number} → now v{updated_file.version}")
    
    return {
        "status": "rolled_back",
        "file_id": file_id,
        "from_version": version_number,
        "to_version": updated_file.version,
        "content_hash": updated_file.content_hash
    }
