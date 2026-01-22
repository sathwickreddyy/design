import boto3
from botocore.exceptions import ClientError
import os
import uuid
import logging
from datetime import datetime
from io import BytesIO


# Configure logger
logger = logging.getLogger(__name__)


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
            buckets: List of bucket names to ensure. Defaults to ['videos', 'encoded']
        """
        if buckets is None:
            buckets = ['videos', 'encoded']
        
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
