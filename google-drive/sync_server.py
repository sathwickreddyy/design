"""
Sync Server with Optimistic Concurrency Control
FastAPI server managing file sync with version-based conflict detection
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, String, Integer, LargeBinary, DateTime, select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv
import os

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


# Database Model
class FileRecord(Base):
    __tablename__ = "files"
    
    file_id = Column(String(255), primary_key=True, index=True)
    content = Column(LargeBinary, nullable=False)
    version = Column(Integer, nullable=False, default=1, index=True)
    content_hash = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


# Pydantic Models
class FileUploadRequest(BaseModel):
    content: str = Field(..., description="File content (base64 or text)")
    expected_version: int = Field(..., description="Expected current version for optimistic locking")
    content_hash: Optional[str] = Field(None, description="SHA256 hash of content for integrity check")


class FileResponse(BaseModel):
    file_id: str
    content: str
    version: int
    content_hash: str
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables created/verified")
    logger.info(f"🌐 Server ready at http://localhost:8000")


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down Sync Server...")
    await engine.dispose()


# Helper functions
def compute_hash(content: bytes) -> str:
    """Compute SHA256 hash of content"""
    return hashlib.sha256(content).hexdigest()


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
    """Download file with current version"""
    logger.info(f"📥 GET /files/{file_id}")
    
    async with async_session_maker() as session:
        result = await session.execute(
            select(FileRecord).where(FileRecord.file_id == file_id)
        )
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            logger.warning(f"❌ File not found: {file_id}")
            raise HTTPException(status_code=404, detail="File not found")
        
        logger.info(f"✅ Returning {file_id} v{file_record.version}")
        return FileResponse(
            file_id=file_record.file_id,
            content=file_record.content.decode('utf-8'),
            version=file_record.version,
            content_hash=file_record.content_hash,
            updated_at=file_record.updated_at
        )


@app.post("/files/{file_id}")
async def upload_file(file_id: str, request: FileUploadRequest):
    """
    Upload file with optimistic locking
    Returns 409 CONFLICT if version mismatch
    """
    logger.info(f"📤 POST /files/{file_id} (expected_version={request.expected_version})")
    
    content_bytes = request.content.encode('utf-8')
    computed_hash = compute_hash(content_bytes)
    
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
    
    async with async_session_maker() as session:
        async with session.begin():
            # First check if file exists (NO LOCK - pure read)
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
                
                file_record = FileRecord(
                    file_id=file_id,
                    content=content_bytes,
                    version=1,
                    content_hash=computed_hash
                )
                session.add(file_record)
                await session.commit()
                
                logger.info(f"✅ Created {file_id} v1")
                return {
                    "status": "created",
                    "file_id": file_id,
                    "version": 1,
                    "content_hash": computed_hash
                }
            
            # **TRUE OPTIMISTIC LOCKING: Atomic UPDATE with WHERE version check**
            # This updates ONLY if version matches - no row locks!
            stmt = (
                update(FileRecord)
                .where(
                    FileRecord.file_id == file_id,
                    FileRecord.version == request.expected_version  # Atomic version check
                )
                .values(
                    content=content_bytes,
                    version=request.expected_version + 1,
                    content_hash=computed_hash,
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
                
                # Re-fetch current state to return to client
                result = await session.execute(
                    select(FileRecord).where(FileRecord.file_id == file_id)
                )
                current_file = result.scalar_one()
                
                conflict_response = ConflictResponse(
                    message=f"Version conflict: expected {request.expected_version}, server has {current_file.version}",
                    current_version=current_file.version,
                    server_content=current_file.content.decode('utf-8'),
                    server_hash=current_file.content_hash
                )
                
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content=conflict_response.model_dump()
                )
            
            # Success - update applied atomically
            new_version = request.expected_version + 1
            logger.info(f"✅ Updated {file_id}: v{request.expected_version} → v{new_version}")
            return {
                "status": "updated",
                "file_id": file_id,
                "version": new_version,
                "content_hash": computed_hash
            }


@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Delete file (for cleanup)"""
    logger.info(f"🗑️ DELETE /files/{file_id}")
    
    async with async_session_maker() as session:
        async with session.begin():
            result = await session.execute(
                select(FileRecord).where(FileRecord.file_id == file_id)
            )
            file_record = result.scalar_one_or_none()
            
            if not file_record:
                raise HTTPException(status_code=404, detail="File not found")
            
            await session.delete(file_record)
            await session.commit()
            
            logger.info(f"✅ Deleted {file_id}")
            return {"status": "deleted", "file_id": file_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVER_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
