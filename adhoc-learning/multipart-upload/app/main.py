"""FastAPI server for multipart upload with resumable sessions."""
import os
import uuid
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
import hashlib

from database import get_db, engine
from models import Base, UploadSession

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Multipart Upload API")

# Directories
TEMP_UPLOAD_DIR = os.getenv("TEMP_UPLOAD_DIR", "/tmp/uploads")
COMPLETED_UPLOAD_DIR = os.getenv("COMPLETED_UPLOAD_DIR", "/data/completed")
Path(TEMP_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(COMPLETED_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


# Request/Response Models
class InitUploadRequest(BaseModel):
    filename: str
    file_size: int
    chunk_size: int = 5242880  # 5MB default
    file_hash: Optional[str] = None  # SHA256 of full file (optional)
    hash_algorithm: str = "SHA256"  # Hash algorithm used


class InitUploadResponse(BaseModel):
    session_id: str
    total_parts: int


class UploadStatusResponse(BaseModel):
    session_id: str
    filename: str
    total_parts: int
    completed_parts: List[int]
    status: str
    progress_percent: float


class CompleteUploadResponse(BaseModel):
    session_id: str
    status: str
    file_path: str
    message: str


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    return {"status": "healthy"}


@app.post("/upload/init", response_model=InitUploadResponse)
async def init_upload(request: InitUploadRequest, db: Session = Depends(get_db)):
    """
    Initialize a multipart upload session.
    
    Creates a unique session ID and prepares temporary storage.
    Calculates total number of parts based on file size and chunk size.
    """
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    
    # Calculate total parts needed
    total_parts = (request.file_size + request.chunk_size - 1) // request.chunk_size
    
    # Create session directory
    session_dir = Path(TEMP_UPLOAD_DIR) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    
    # Store session metadata in database
    session = UploadSession(
        session_id=session_id,
        filename=request.filename,
        file_size=request.file_size,
        chunk_size=request.chunk_size,
        total_parts=total_parts,
        completed_parts=[],
        file_hash=request.file_hash,
        hash_algorithm=request.hash_algorithm,
        part_hashes={},
        status="in_progress"
    )
    
    db.add(session)
    db.commit()
    
    logger.info(f"Initialized upload session {session_id} for {request.filename} ({total_parts} parts)")
    
    return InitUploadResponse(
        session_id=session_id,
        total_parts=total_parts
    )


@app.put("/upload/{session_id}/part/{part_number}")
async def upload_part(
    session_id: str,
    part_number: int,
    file: UploadFile = File(...),
    x_part_hash: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Upload a single part of the file with MD5 checksum verification.
    
    Idempotent: Uploading the same part twice will overwrite the previous one.
    This is critical for retry logic on network failures.
    
    Args:
        x_part_hash: Optional MD5 hash of the part. If provided, part is verified.
    """
    # Verify session exists
    session = db.query(UploadSession).filter(UploadSession.session_id == session_id).first()
    if not session:
        logger.error(f"Session {session_id} not found")
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    if session.status != "in_progress":
        logger.error(f"Session {session_id} is not in progress (status: {session.status})")
        raise HTTPException(status_code=400, detail=f"Upload session is {session.status}")
    
    # Validate part number
    if part_number < 1 or part_number > session.total_parts:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid part number. Must be between 1 and {session.total_parts}"
        )
    
    # Save part to temp storage
    session_dir = Path(TEMP_UPLOAD_DIR) / session_id
    part_path = session_dir / f"part_{part_number}"
    
    try:
        # Write chunk to disk
        content = await file.read()
        with open(part_path, "wb") as f:
            f.write(content)
        
        # Verify part hash if provided
        if x_part_hash:
            part_md5 = hashlib.md5(content).hexdigest()
            if part_md5.lower() != x_part_hash.lower():
                logger.error(f"Checksum mismatch for part {part_number}: expected {x_part_hash}, got {part_md5}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Checksum mismatch for part {part_number}"
                )
            logger.info(f"Part {part_number} checksum verified: {part_md5}")
        
        # Update completed parts and store part hash using SQL-level atomic operation
        # This prevents race conditions when multiple parts upload simultaneously
        part_md5 = hashlib.md5(content).hexdigest()
        db.execute(
            text("""
                UPDATE upload_sessions
                SET completed_parts = array_append(completed_parts, :part_num),
                    part_hashes = jsonb_set(part_hashes, ARRAY[:part_key], :part_hash)
                WHERE session_id = :session_id
                  AND NOT :part_num = ANY(completed_parts)
            """),
            {
                "session_id": session_id,
                "part_num": part_number,
                "part_key": str(part_number),
                "part_hash": f'"{part_md5}"'
            }
        )
        db.commit()
        
        logger.info(f"Uploaded part {part_number}/{session.total_parts} for session {session_id}")
        
        return {
            "part_number": part_number,
            "received": True,
            "size": len(content),
            "checksum": part_md5
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload part {part_number} for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/upload/{session_id}/status", response_model=UploadStatusResponse)
async def get_upload_status(session_id: str, db: Session = Depends(get_db)):
    """
    Get the current status of an upload session.
    
    Returns which parts have been successfully uploaded.
    Client uses this to resume from failure point.
    """
    session = db.query(UploadSession).filter(UploadSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    progress_percent = (len(session.completed_parts) / session.total_parts * 100) if session.total_parts > 0 else 0
    
    return UploadStatusResponse(
        session_id=session.session_id,
        filename=session.filename,
        total_parts=session.total_parts,
        completed_parts=sorted(session.completed_parts),
        status=session.status,
        progress_percent=round(progress_percent, 2)
    )


@app.post("/upload/{session_id}/complete", response_model=CompleteUploadResponse)
async def complete_upload(session_id: str, db: Session = Depends(get_db)):
    """
    Complete the multipart upload.
    
    Assembles all parts into final file and cleans up temp storage.
    """
    logger.info(f"Starting completion for upload session {session_id}")
    session = db.query(UploadSession).filter(UploadSession.session_id == session_id).first()
    logger.info(f"Fetched session from DB: {bool(session)}")
    if not session:
        logger.info(f"Session {session_id} not found, raising 404")
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session.status == "completed":
        logger.info(f"Session {session_id} already completed")
        return CompleteUploadResponse(
            session_id=session_id,
            status="completed",
            file_path=f"{COMPLETED_UPLOAD_DIR}/{session.filename}",
            message="Upload already completed"
        )

    logger.info(f"Verifying all parts are uploaded for session {session_id}")
    # Verify all parts are uploaded
    if len(session.completed_parts) != session.total_parts:
        missing_parts = set(range(1, session.total_parts + 1)) - set(session.completed_parts)
        logger.info(f"Missing parts for session {session_id}: {sorted(missing_parts)}")
        raise HTTPException(
            status_code=400,
            detail=f"Missing parts: {sorted(missing_parts)}"
        )

    session_dir = Path(TEMP_UPLOAD_DIR) / session_id
    final_path = Path(COMPLETED_UPLOAD_DIR) / session.filename
    logger.info(f"Session dir: {session_dir}, Final path: {final_path}")

    try:
        logger.info(f"Assembling parts for session {session_id}")
        # Assemble parts in order
        with open(final_path, "wb") as outfile:
            for part_num in range(1, session.total_parts + 1):
                part_path = session_dir / f"part_{part_num}"
                logger.info(f"Processing part {part_num}: {part_path}")
                if not part_path.exists():
                    logger.info(f"Part {part_num} file not found for session {session_id}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Part {part_num} file not found"
                    )
                with open(part_path, "rb") as infile:
                    data = infile.read()
                    outfile.write(data)
                    logger.info(f"Written part {part_num} ({len(data)} bytes) to final file for session {session_id}")

        logger.info(f"All parts assembled for session {session_id}")
        
        # Verify full file hash if provided
        if session.file_hash:
            logger.info(f"Verifying file integrity for session {session_id}")
            file_sha256 = hashlib.sha256()
            with open(final_path, "rb") as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    file_sha256.update(chunk)
            
            computed_hash = file_sha256.hexdigest()
            if computed_hash.lower() != session.file_hash.lower():
                logger.error(f"File hash mismatch for session {session_id}: expected {session.file_hash}, got {computed_hash}")
                session.status = "failed"
                db.commit()
                raise HTTPException(
                    status_code=400,
                    detail=f"File integrity check failed. Hash mismatch."
                )
            logger.info(f"File hash verified: {computed_hash}")
        
        # Update session status
        session.status = "completed"
        session.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Session {session_id} marked as completed in DB")

        # Cleanup temp files
        shutil.rmtree(session_dir)
        logger.info(f"Cleaned up temp files for session {session_id}")

        logger.info(f"Completed upload for session {session_id}, file saved to {final_path}")

        return CompleteUploadResponse(
            session_id=session_id,
            status="completed",
            file_path=str(final_path),
            message=f"File {session.filename} uploaded successfully"
        )

    except Exception as e:
        logger.error(f"Failed to complete upload for session {session_id}: {e}")
        session.status = "failed"
        db.commit()
        logger.info(f"Session {session_id} marked as failed in DB")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/upload/{session_id}")
async def cancel_upload(session_id: str, db: Session = Depends(get_db)):
    """
    Cancel an upload session and cleanup resources.
    
    Useful for handling abandoned uploads or user cancellation.
    """
    session = db.query(UploadSession).filter(UploadSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Cleanup temp files
    session_dir = Path(TEMP_UPLOAD_DIR) / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    
    # Update status
    session.status = "cancelled"
    db.commit()
    
    logger.info(f"Cancelled upload session {session_id}")
    
    return {"session_id": session_id, "status": "cancelled"}


@app.get("/sessions")
async def list_sessions(status: str = None, db: Session = Depends(get_db)):
    """
    List all upload sessions, optionally filtered by status.
    
    Useful for debugging and monitoring.
    """
    query = db.query(UploadSession)
    if status:
        query = query.filter(UploadSession.status == status)
    
    sessions = query.order_by(UploadSession.created_at.desc()).all()
    
    return {
        "total": len(sessions),
        "sessions": [
            {
                "session_id": s.session_id,
                "filename": s.filename,
                "status": s.status,
                "progress": f"{len(s.completed_parts)}/{s.total_parts}",
                "created_at": s.created_at.isoformat()
            }
            for s in sessions
        ]
    }
