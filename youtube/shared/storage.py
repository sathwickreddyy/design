import boto3
from botocore.exceptions import ClientError
import os
import uuid
import logging
import json
from datetime import datetime
from io import BytesIO


# Configure logger
logger = logging.getLogger(__name__)


# Storage path constants for consistent structure
class StoragePaths:
    """
    Centralized storage path definitions.
    
    Structure (all under videos bucket):
        videos/{video_id}/
            source/
                source.mp4
                chunks/
                    chunk_0000.mp4, chunk_0001.mp4, ...
                manifest.json
            outputs/
                720p/
                    segments/
                        seg_0000.mp4, seg_0001.mp4, ...
                    {video_id}_720p.mp4  (final merged)
                480p/...
                320p/...
    """
    
    @staticmethod
    def source_video(video_id: str) -> str:
        """Path to original uploaded video."""
        return f"{video_id}/source/source.mp4"
    
    @staticmethod
    def source_chunk(video_id: str, chunk_index: int) -> str:
        """Path to a source chunk."""
        return f"{video_id}/source/chunks/chunk_{chunk_index:04d}.mp4"
    
    @staticmethod
    def source_manifest(video_id: str) -> str:
        """Path to source chunks manifest."""
        return f"{video_id}/source/manifest.json"
    
    @staticmethod
    def output_segment(video_id: str, resolution: str, segment_index: int) -> str:
        """Path to a transcoded HLS segment (.ts for streaming)."""
        return f"{video_id}/outputs/{resolution}/segments/seg_{segment_index:04d}.ts"
    
    @staticmethod
    def output_manifest(video_id: str, resolution: str) -> str:
        """Path to output manifest for a resolution."""
        return f"{video_id}/outputs/{resolution}/manifest.json"
    
    @staticmethod
    def variant_playlist(video_id: str, resolution: str) -> str:
        """Path to HLS variant playlist for a specific resolution."""
        return f"{video_id}/outputs/{resolution}/playlist.m3u8"
    
    @staticmethod
    def master_playlist(video_id: str) -> str:
        """Path to HLS master playlist (adaptive bitrate index)."""
        return f"{video_id}/outputs/master.m3u8"
    
    @staticmethod
    def final_video(video_id: str, resolution: str) -> str:
        """Path to final merged video (same bucket, under outputs). DEPRECATED: Use HLS playlists instead."""
        return f"{video_id}/outputs/{resolution}/{video_id}_{resolution}.mp4"
    
    # ==================== Thumbnail Paths ====================
    
    @staticmethod
    def thumbnail(video_id: str) -> str:
        """Path to video thumbnail (in thumbnails bucket)."""
        return f"{video_id}/thumbnail.jpg"
    
    @staticmethod
    def custom_thumbnail_upload(video_id: str, filename: str) -> str:
        """Path for user-uploaded custom thumbnail."""
        return f"{video_id}/custom/{filename}"
    
    # ==================== Chapter/Scene Paths ====================
    
    @staticmethod
    def chapters_json(video_id: str) -> str:
        """Path to chapters metadata JSON file."""
        return f"{video_id}/outputs/chapters.json"
    
    @staticmethod
    def chapters_vtt(video_id: str) -> str:
        """Path to WebVTT chapters file for HTML5 players."""
        return f"{video_id}/outputs/chapters.vtt"
    
    @staticmethod
    def chapters_hls(video_id: str) -> str:
        """Path to HLS chapter tags file."""
        return f"{video_id}/outputs/chapters_hls.txt"
    
    # ==================== Processing Metadata ====================
    
    @staticmethod
    def processing_status(video_id: str) -> str:
        """Path to processing status/result metadata."""
        return f"{video_id}/outputs/processing_status.json"


class MinIOStorage:
    """Utility class for MinIO storage operations"""
    
    def __init__(
        self,
        endpoint_url: str = None,
        access_key: str = None,
        secret_key: str = None,
        region_name: str = "us-east-1",
        auto_create_buckets: bool = True
    ):
        """
        Initialize MinIO client
        
        Args:
            endpoint_url: MinIO server endpoint (defaults to MINIO_ENDPOINT env var or http://localhost:9000)
            access_key: Access key for MinIO (defaults to MINIO_ACCESS_KEY env var or 'admin')
            secret_key: Secret key for MinIO (defaults to MINIO_SECRET_KEY env var or 'password123')
            region_name: AWS region (required by boto3)
        """
        # Use env variables with fallbacks
        self.endpoint_url = endpoint_url or os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "admin")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "password123")
        
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=region_name
        )
        
        # Auto-create required buckets on initialization
        if auto_create_buckets:
            self.ensure_buckets()
    
    def file_exists(self, bucket_name: str, object_name: str) -> bool:
        """Check if a file exists in the bucket"""
        try:
            self.s3_client.head_object(Bucket=bucket_name, Key=object_name)
            return True
        except ClientError:
            return False
    
    def upload_fileobj(self, file_data: bytes, bucket_name: str, object_name: str) -> bool:
        """
        Upload file data (bytes) directly to MinIO without saving to disk
        
        Args:
            file_data: File content as bytes
            bucket_name: Name of the bucket
            object_name: Name of the object in bucket
            
        Returns:
            True if upload successful, False otherwise
        """
        try:
            file_obj = BytesIO(file_data)
            self.s3_client.upload_fileobj(file_obj, bucket_name, object_name)
            logger.info(f"File data uploaded to '{bucket_name}/{object_name}'")
            return True
        except ClientError as e:
            logger.error(f"Error uploading file data: {e}")
            return False
    
    def ensure_buckets(self, buckets: list = None) -> None:
        """
        Ensure required buckets exist, create if missing
        
        Args:
            buckets: List of bucket names to ensure. Defaults to ['videos', 'encoded', 'thumbnails']
        """
        if buckets is None:
            buckets = ['videos', 'encoded', 'thumbnails']
        
        for bucket in buckets:
            self.create_bucket(bucket)
    
    def create_bucket(self, bucket_name: str) -> bool:
        """
        Create a bucket in MinIO
        
        Args:
            bucket_name: Name of the bucket to create
            
        Returns:
            True if bucket created successfully, False if it already exists
        """
        try:
            self.s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' created successfully")
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
                logger.info(f"Bucket '{bucket_name}' already exists")
                return False
            else:
                logger.error(f"Error creating bucket: {e}")
                raise
    
    def _generate_video_id(self) -> str:
        """
        Generate a unique video ID
        
        Returns:
            Unique video ID with timestamp prefix
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        return f"{timestamp}_{unique_id}"
    
    def upload_raw_file(self, file_path: str, bucket_name: str = "videos") -> tuple[str, bool]:
        """
        Upload a raw video file and generate a unique video ID
        
        Args:
            file_path: Path to the local video file
            bucket_name: Name of the bucket (default: "videos")
            
        Returns:
            Tuple of (video_id, success) - video_id is the unique identifier for the video
        """
        video_id = self._generate_video_id()
        
        try:
            self.s3_client.upload_file(file_path, bucket_name, video_id)
            logger.info(f"Raw video uploaded to '{bucket_name}/{video_id}'")
            return video_id, True
        except ClientError as e:
            logger.error(f"Error uploading raw file: {e}")
            return None, False
    
    def upload_file(self, file_path: str, bucket_name: str, object_name: str = None, video_id: str = None, suffix: str = None) -> bool:
        """
        Upload a file to MinIO
        
        Args:
            file_path: Path to the local file
            bucket_name: Name of the bucket
            object_name: Name of the object in bucket (if None, uses file name)
            video_id: Optional video ID to use as prefix (for encoded/transcoded videos)
            suffix: Optional suffix to append to video_id (e.g., "_720p", "_audio")
            
        Returns:
            True if upload successful, False otherwise
        """
        if object_name is None:
            if video_id:
                # For encoded/transcoded videos: video_id_suffix
                object_name = video_id + (f"_{suffix}" if suffix else "")
            else:
                # Default: use file name
                object_name = os.path.basename(file_path)
        
        try:
            self.s3_client.upload_file(file_path, bucket_name, object_name)
            logger.info(f"File '{file_path}' uploaded to '{bucket_name}/{object_name}'")
            return True
        except ClientError as e:
            logger.error(f"Error uploading file: {e}")
            return False
    
    def download_file(self, bucket_name: str, object_name: str, file_path: str) -> bool:
        """
        Download a file from MinIO
        
        Args:
            bucket_name: Name of the bucket
            object_name: Name of the object in bucket
            file_path: Local path to save the file
            
        Returns:
            True if download successful, False otherwise
        """
        try:
            self.s3_client.download_file(bucket_name, object_name, file_path)
            logger.info(f"File '{object_name}' downloaded from '{bucket_name}' to '{file_path}'")
            return True
        except ClientError as e:
            logger.error(f"Error downloading file: {e}")
            return False
    
    def list_objects(self, bucket_name: str, prefix: str = "") -> list:
        """
        List objects in a bucket
        
        Args:
            bucket_name: Name of the bucket
            prefix: Filter objects by prefix
            
        Returns:
            List of object names
        """
        try:
            response = self.s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
            if 'Contents' not in response:
                return []
            return [obj['Key'] for obj in response['Contents']]
        except ClientError as e:
            logger.error(f"Error listing objects: {e}")
            return []
    
    def delete_file(self, bucket_name: str, object_name: str) -> bool:
        """
        Delete a file from MinIO
        
        Args:
            bucket_name: Name of the bucket
            object_name: Name of the object to delete
            
        Returns:
            True if deletion successful, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=bucket_name, Key=object_name)
            logger.info(f"File '{object_name}' deleted from '{bucket_name}'")
            return True
        except ClientError as e:
            logger.error(f"Error deleting file: {e}")
            return False
    
    def get_object_url(self, bucket_name: str, object_name: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for an object
        
        Args:
            bucket_name: Name of the bucket
            object_name: Name of the object
            expiration: URL expiration time in seconds (default: 1 hour)
            
        Returns:
            Presigned URL
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating URL: {e}")
            return None
