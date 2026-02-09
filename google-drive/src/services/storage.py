"""
MinIO storage service with bucketed content-addressed storage
"""
import hashlib
import logging
from pathlib import Path
from typing import AsyncIterator

from minio import Minio
from minio.error import S3Error

from ..core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Object storage service using MinIO (S3-compatible) with content-addressed storage.
    
    Key features:
    - Bucketed storage keys for even distribution (v1/contents/a3/f7/hash...)
    - Content deduplication via hash-based keys
    - Streaming uploads/downloads for constant memory usage
    """
    
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self.bucket = settings.MINIO_BUCKET
        logger.info(f"🗄️  MinIO client initialized: {settings.MINIO_ENDPOINT}/{self.bucket}")
    
    def ensure_bucket_exists(self):
        """Create bucket if it doesn't exist"""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"✅ Created MinIO bucket: {self.bucket}")
            else:
                logger.info(f"✅ MinIO bucket exists: {self.bucket}")
        except S3Error as e:
            logger.error(f"❌ Failed to create bucket: {e}")
            raise
    
    def generate_storage_key(self, content_hash: str) -> str:
        """
        Generate bucketed storage key from content hash (industry best practice).
        
        Format: v1/contents/{hash[0:2]}/{hash[2:4]}/{hash}
        Example: v1/contents/a3/f7/a3f7c2e9d8b1c7f2a9e5d1b8c3f7a2e9...
        
        Bucketing strategy (AWS S3 best practice):
        - First 2 chars: 256 possible values (00-ff)
        - Next 2 chars: 256 possible values (00-ff)
        - Total: 65,536 unique prefixes
        - Distributes load evenly across S3 partitions
        - Avoids hot partition problems
        - Better throughput at scale
        
        Args:
            content_hash: SHA256 hash of file content
            
        Returns:
            Bucketed storage key path
        """
        return f"v1/contents/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"
    
    def exists(self, storage_key: str) -> bool:
        """Check if object exists in storage"""
        try:
            self.client.stat_object(self.bucket, storage_key)
            return True
        except S3Error:
            return False
    
    def upload(self, storage_key: str, content: bytes) -> None:
        """
        Upload content to storage (synchronous, for small files).
        
        For large files, use upload_streaming() instead.
        """
        from io import BytesIO
        
        self.client.put_object(
            self.bucket,
            storage_key,
            BytesIO(content),
            length=len(content)
        )
        logger.info(f"✅ Uploaded {len(content)} bytes to {storage_key}")
    
    async def upload_streaming(
        self,
        storage_key: str,
        content_stream: AsyncIterator[bytes]
    ) -> tuple[str, int]:
        """
        Upload content from async stream with hash computation (single-pass).
        
        This method:
        1. Reads from async stream in chunks
        2. Computes SHA256 hash incrementally
        3. Uploads to MinIO
        4. Returns (content_hash, total_size)
        
        Benefits:
        - Constant memory usage (only 8KB chunk in RAM at a time)
        - Single pass through data (compute hash while uploading)
        - Works for files of any size
        
        Args:
            storage_key: Where to store (can be temp location)
            content_stream: Async iterator yielding bytes
            
        Returns:
            (content_hash, size_bytes) tuple
        """
        import tempfile
        import asyncio
        from pathlib import Path
        
        hasher = hashlib.sha256()
        total_size = 0
        
        # Write to temp file while computing hash
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                async for chunk in content_stream:
                    hasher.update(chunk)
                    total_size += len(chunk)
                    tmp.write(chunk)
                
                tmp.flush()
                
                # Compute final hash
                content_hash = hasher.hexdigest()
                final_storage_key = self.generate_storage_key(content_hash)
                
                # Check if content already exists (deduplication)
                if not self.exists(final_storage_key):
                    # Upload to MinIO (blocking call, run in executor)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        self._upload_file,
                        tmp_path,
                        final_storage_key,
                        total_size
                    )
                    logger.info(f"✅ Uploaded {total_size} bytes to {final_storage_key}")
                else:
                    logger.info(f"⚡ Deduplication: {final_storage_key} already exists, skipped upload")
                
                return content_hash, total_size
                
            finally:
                # Cleanup temp file
                tmp_path.unlink(missing_ok=True)
    
    def _upload_file(self, file_path: Path, storage_key: str, size: int):
        """Helper: Upload file from disk (sync)"""
        self.client.fput_object(self.bucket, storage_key, str(file_path))
    
    def download(self, storage_key: str) -> bytes:
        """
        Download content from storage (synchronous, loads entire file to memory).
        
        For large files, use get_object() + stream reading instead.
        """
        try:
            response = self.client.get_object(self.bucket, storage_key)
            content = response.read()
            response.close()
            logger.info(f"✅ Downloaded {len(content)} bytes from {storage_key}")
            return content
        except S3Error as e:
            logger.error(f"❌ Failed to download {storage_key}: {e}")
            raise
    
    def delete(self, storage_key: str) -> None:
        """
        Delete object from storage.
        
        Note: With content-addressed storage, only delete if no other files reference it.
        Typically we DON'T delete content (keep for deduplication).
        """
        try:
            self.client.remove_object(self.bucket, storage_key)
            logger.info(f"🗑️  Deleted {storage_key}")
        except S3Error as e:
            logger.error(f"❌ Failed to delete {storage_key}: {e}")
            raise


# Singleton instance
storage_service = StorageService()
