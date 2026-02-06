"""
Sync Server with Optimistic Concurrency Control + Object Storage
FastAPI server managing file sync with version-based conflict detection
- Metadata in PostgreSQL
- Content in MinIO (S3-compatible)
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional
import io

from fastapi import FastAPI, HTTPException, status, UploadFile, File as FastAPIFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Integer, BigInteger, DateTime, select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv
import os
from minio import Minio
from minio.error import S3Error

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("sync_server")

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://syncuser:syncpass@localhost:5432/syncdb")
engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# MinIO setup
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "sync-files")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


# Database Model (Metadata only - no content!)
class FileRecord(Base):
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


# Pydantic Models
class FileUploadRequest(BaseModel):
    content: str = Field(..., description="File content (base64 or text)")
    expected_version: int = Field(..., description="Expected current version for optimistic locking")
    content_hash: Optional[str] = Field(None, description="SHA256 hash of content for integrity check")


class FileMetadataResponse(BaseModel):
    file_id: str
    version: int
    content_hash: str
    size_bytes: int
    mime_type: str
    storage_key: str
    updated_at: datetime


class FileResponse(BaseModel):
    file_id: str
    content: str
    version: int
    content_hash: str
    size_bytes: int
    updated_at: datetime


class ConflictResponse(BaseModel):
    error: str = "CONFLICT"
    message: str
    current_version: int
    server_content: str
    server_hash: str


# FastAPI app
app = FastAPI(
    title="Sync Conflict Resolver",
    description="File sync system with optimistic concurrency control",
    version="1.0.0"
)


# Database initialization
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting Sync Server...")
    
    # Initialize database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables created/verified")
    
    # Initialize MinIO bucket
    try:
        if not minio_client.bucket_exists(MINIO_BUCKET):
            minio_client.make_bucket(MINIO_BUCKET)
            logger.info(f"✅ Created MinIO bucket: {MINIO_BUCKET}")
        else:
            logger.info(f"✅ MinIO bucket exists: {MINIO_BUCKET}")
    except S3Error as e:
        logger.error(f"❌ MinIO initialization failed: {e}")
        raise
    
    logger.info(f"🌐 Server ready at http://localhost:8000")
    logger.info(f"📦 MinIO console at http://localhost:9001")


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down Sync Server...")
    await engine.dispose()


# Helper functions
def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content"""
    return hashlib.sha256(content).hexdigest()


def generate_storage_key(file_id: str, version: int, content_hash: str) -> str:
    """Generate MinIO storage key for file version"""
    return f"{content_hash[:8]}/{file_id}/v{version}"


def upload_to_minio(storage_key: str, content: bytes) -> None:
    """Upload content to MinIO"""
    try:
        minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=storage_key,
            data=io.BytesIO(content),
            length=len(content)
        )
        logger.info(f"📤 Uploaded to MinIO: {storage_key}")
    except S3Error as e:
        logger.error(f"❌ MinIO upload failed for {storage_key}: {e}")
        raise


def download_from_minio(storage_key: str) -> bytes:
    """Download content from MinIO"""
    try:
        response = minio_client.get_object(MINIO_BUCKET, storage_key)
        content = response.read()
        response.close()
        response.release_conn()
        logger.info(f"📥 Downloaded from MinIO: {storage_key}")
        return content
    except S3Error as e:
        logger.error(f"❌ MinIO download failed for {storage_key}: {e}")
        raise


def delete_from_minio(storage_key: str) -> None:
    """Delete object from MinIO"""
    try:
        minio_client.remove_object(MINIO_BUCKET, storage_key)
        logger.info(f"🗑️ Deleted from MinIO: {storage_key}")
    except S3Error as e:
        logger.warning(f"⚠️ MinIO delete failed for {storage_key}: {e}")


# API Endpoints
@app.get("/")
async def root():
    return {
        "service": "Sync Conflict Resolver",
        "status": "running",
        "docs": "/docs"
    }


@app.get("/files", response_model=list[dict])
async def list_files():
    """List all files in the system"""
    logger.info("📋 Listing all files")
    async with async_session_maker() as session:
        result = await session.execute(select(FileRecord))
        files = result.scalars().all()
        return [
            {
                "file_id": f.file_id,
                "version": f.version,
                "content_hash": f.content_hash,
                "updated_at": f.updated_at.isoformat()
            }
            for f in files
        ]


@app.get("/files/{file_id}", response_model=FileResponse)
async def get_file(file_id: str):
    """Download file content from object storage"""
    logger.info(f"📥 GET /files/{file_id}")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            logger.warning(f"❌ File not found: {file_id}")
            raise HTTPException(status_code=404, detail="File not found")
        
        # Download content from MinIO
        try:
            content_bytes = download_from_minio(file_record.storage_key)
        except S3Error as e:
            logger.error(f"❌ Failed to download {file_id} from MinIO: {e}")
            raise HTTPException(status_code=500, detail="Failed to retrieve file content")
        
        logger.info(f"✅ Returning {file_id} v{file_record.version}")
        return FileResponse(
            file_id=file_record.file_id,
            content=content_bytes.decode('utf-8'),
            version=file_record.version,
            content_hash=file_record.content_hash,
            size_bytes=file_record.size_bytes,
            updated_at=file_record.updated_at
        )


@app.get("/files/{file_id}/metadata", response_model=FileMetadataResponse)
async def get_file_metadata(file_id: str):
    """Get file metadata without downloading content"""
    logger.info(f"📋 GET /files/{file_id}/metadata")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        file_record = result.scalar_one_or_none()
        
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


@app.post("/files/{file_id}")
async def upload_file(file_id: str, request: FileUploadRequest):
    """
    Upload file with optimistic locking (content to MinIO, metadata to Postgres)
    Returns 409 CONFLICT if version mismatch
    """
    logger.info(f"📤 POST /files/{file_id} (expected_version={request.expected_version})")
    
    content_bytes = request.content.encode('utf-8')
    computed_hash = compute_hash(content_bytes)
    new_version = request.expected_version + 1
    
    # Validate hash if provided
    if request.content_hash and request.content_hash != computed_hash:
        logger.error(f"❌ Hash mismatch for {file_id}")
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INTEGRITY_ERROR",
                "message": "Content hash mismatch",
                "expected": request.content_hash,
                "computed": computed_hash
            }
        )
    
    # Generate storage key for MinIO
    storage_key = generate_storage_key(file_id, new_version, computed_hash)
    
    async with async_session_maker() as session:
        async with session.begin():
            # Check if file exists (NO LOCK - pure read)
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            file_record = result.scalar_one_or_none()
            
            # Create new file if doesn't exist
            if not file_record:
                if request.expected_version != 0:
                    logger.warning(f"⚠️ New file {file_id} but expected_version={request.expected_version}")
                    raise HTTPException(
                        status_code=400,
                        detail="New file must have expected_version=0"
                    )
                
                # Upload to MinIO FIRST (idempotent)
                upload_to_minio(storage_key, content_bytes)
                
                # Create metadata record
                file_record = FileRecord(
                    file_id=file_id,
                    version=1,
                    storage_key=storage_key,
                    content_hash=computed_hash,
                    size_bytes=len(content_bytes),
                    mime_type="text/plain"
                )
                session.add(file_record)
                await session.commit()
                
                logger.info(f"✅ Created {file_id} v1 (MinIO: {storage_key})")
                return {
                    "status": "created",
                    "file_id": file_id,
                    "version": 1,
                    "content_hash": computed_hash,
                    "storage_key": storage_key
                }
            
            # Upload to MinIO BEFORE metadata update (idempotent, can retry safely)
            try:
                upload_to_minio(storage_key, content_bytes)
            except Exception as e:
                logger.error(f"❌ Failed to upload to MinIO: {e}")
                raise HTTPException(status_code=500, detail="Failed to upload file content")
            
            # **TRUE OPTIMISTIC LOCKING: Atomic UPDATE with WHERE version check**
            # This updates ONLY if version matches - no row locks!
            stmt = (
                update(FileRecord)
                .where(
                    FileRecord.file_id == file_id,
                    FileRecord.version == request.expected_version  # Atomic version check
                )
                .values(
                    storage_key=storage_key,
                    version=new_version,
                    content_hash=computed_hash,
                    size_bytes=len(content_bytes),
                    updated_at=datetime.utcnow()
                )
            )
            
            result = await session.execute(stmt)
            await session.commit()
            
            # Check if update actually happened (rowcount == 0 means version mismatch)
            if result.rowcount == 0:
                # Version changed between read and write - CONFLICT!
                logger.warning(
                    f"⚠️ CONFLICT detected for {file_id}: "
                    f"expected v{request.expected_version}, but version changed during operation"
                )
                
                # Clean up MinIO upload (conflict means we won't use it)
                delete_from_minio(storage_key)
                
                # Re-fetch current state to return to client
                result = await session.execute(
                    select(FileRecord).where(FileRecord.file_id == file_id)
                )
                current_file = result.scalar_one()
                
                # Download current content from MinIO to return in conflict response
                try:
                    current_content_bytes = download_from_minio(current_file.storage_key)
                    current_content = current_content_bytes.decode('utf-8')
                except Exception as e:
                    logger.error(f"❌ Failed to download current version: {e}")
                    current_content = "<content unavailable>"
                
                conflict_response = ConflictResponse(
                    message=f"Version conflict: expected {request.expected_version}, server has {current_file.version}",
                    current_version=current_file.version,
                    server_content=current_content,
                    server_hash=current_file.content_hash
                )
                
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content=conflict_response.model_dump()
                )
            
            # Success - update applied atomically
            logger.info(f"✅ Updated {file_id}: v{request.expected_version} → v{new_version} (MinIO: {storage_key})")
            return {
                "status": "updated",
                "file_id": file_id,
                "version": new_version,
                "content_hash": computed_hash,
                "storage_key": storage_key
            }


@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Delete file from both metadata and object storage"""
    logger.info(f"🗑️ DELETE /files/{file_id}")
    
    async with async_session_maker() as session:
        async with session.begin():
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            file_record = result.scalar_one_or_none()
            
            if not file_record:
                raise HTTPException(status_code=404, detail="File not found")
            
            # Delete from MinIO first
            delete_from_minio(file_record.storage_key)
            
            # Delete metadata
            await session.delete(file_record)
            await session.commit()
            
            logger.info(f"✅ Deleted {file_id} (metadata + object storage)")
            return {"status": "deleted", "file_id": file_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVER_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
