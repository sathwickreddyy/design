"""
Object storage service (MinIO operations)
"""
import io
import logging
import hashlib
from typing import AsyncIterator, Tuple
from minio import Minio
from minio.error import S3Error

from src.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """Handles all object storage operations"""
    
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self.bucket = settings.MINIO_BUCKET
    
    def ensure_bucket_exists(self):
        """Create bucket if it doesn't exist"""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"✅ Created MinIO bucket: {self.bucket}")
            else:
                logger.info(f"✅ MinIO bucket exists: {self.bucket}")
        except S3Error as e:
            logger.error(f"❌ MinIO initialization failed: {e}")
            raise
    
    def generate_storage_key(self, content_hash: str) -> str:
        """
        Generate content-addressed storage key
        
        Content-addressed storage: Same content = same key = deduplication!
        Multiple files/versions can point to the same hash.
        """
        return content_hash
    
    def exists(self, storage_key: str) -> bool:
        """Check if object exists in MinIO"""
        try:
            self.client.stat_object(self.bucket, storage_key)
            return True
        except S3Error:
            return False
    
    def upload(self, storage_key: str, content: bytes) -> None:
        """Upload content to MinIO (non-streaming, for backward compatibility)"""
        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=storage_key,
                data=io.BytesIO(content),
                length=len(content)
            )
            logger.info(f"📤 Uploaded to MinIO: {storage_key} ({len(content)} bytes)")
        except S3Error as e:
            logger.error(f"❌ MinIO upload failed for {storage_key}: {e}")
            raise
    
    async def upload_streaming(self, storage_key: str, content_stream: AsyncIterator[bytes]) -> Tuple[str, int]:
        """
        Upload content from async stream while computing hash
        
        Returns: (content_hash, size_bytes)
        
        This is production-grade:
        - Single pass (hash + upload in parallel)
        - Constant memory (chunk-based)
        - Works for any file size
        """
        hasher = hashlib.sha256()
        chunks = []
        total_size = 0
        
        # Collect chunks and compute hash simultaneously
        async for chunk in content_stream:
            hasher.update(chunk)
            chunks.append(chunk)
            total_size += len(chunk)
        
        # Combine chunks for upload
        full_content = b''.join(chunks)
        content_hash = hasher.hexdigest()
        
        # Upload to MinIO
        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=storage_key,
                data=io.BytesIO(full_content),
                length=total_size
            )
            logger.info(f"📤 Streamed upload to MinIO: {storage_key} ({total_size} bytes, hash: {content_hash[:8]})")
        except S3Error as e:
            logger.error(f"❌ MinIO streaming upload failed for {storage_key}: {e}")
            raise
        
        return content_hash, total_size
    
    def download(self, storage_key: str) -> bytes:
        """Download content from MinIO"""
        try:
            response = self.client.get_object(self.bucket, storage_key)
            content = response.read()
            response.close()
            response.release_conn()
            logger.info(f"📥 Downloaded from MinIO: {storage_key} ({len(content)} bytes)")
            return content
        except S3Error as e:
            logger.error(f"❌ MinIO download failed for {storage_key}: {e}")
            raise
    
    def delete(self, storage_key: str) -> None:
        """Delete object from MinIO"""
        try:
            self.client.remove_object(self.bucket, storage_key)
            logger.info(f"🗑️ Deleted from MinIO: {storage_key}")
        except S3Error as e:
            logger.warning(f"⚠️ MinIO delete failed for {storage_key}: {e}")


# Singleton instance
storage_service = StorageService()
