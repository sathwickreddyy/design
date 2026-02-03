"""Multipart upload client with parallel workers and checksum verification."""
import os
import sys
import time
import requests
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
CHUNK_SIZE = 5 * 1024 * 1024  # 5MB
MAX_WORKERS = 4  # Parallel upload threads


class MultipartUploader:
    """Client for uploading large files using multipart upload with checksums."""
    
    def __init__(self, api_url: str = API_BASE_URL, chunk_size: int = CHUNK_SIZE, max_workers: int = MAX_WORKERS):
        self.api_url = api_url
        self.chunk_size = chunk_size
        self.max_workers = max_workers
    
    @staticmethod
    def calculate_file_hash(file_path: str, algorithm: str = "SHA256") -> str:
        """Calculate hash of entire file."""
        hash_obj = hashlib.new(algorithm.lower())
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64KB chunks
                if not chunk:
                    break
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    
    @staticmethod
    def calculate_part_hash(data: bytes, algorithm: str = "MD5") -> str:
        """Calculate hash of a part."""
        return hashlib.new(algorithm.lower()).update(data) or hashlib.new(algorithm.lower(), data).hexdigest()
    
    def init_upload(self, filename: str, file_size: int, file_hash: str = None) -> Tuple[str, int]:
        """Initialize upload session and get session ID."""
        print(f"Initializing upload for {filename} ({file_size / (1024*1024):.2f} MB)...")
        if file_hash:
            print(f"  File SHA256: {file_hash[:16]}...")
        
        response = requests.post(
            f"{self.api_url}/upload/init",
            json={
                "filename": filename,
                "file_size": file_size,
                "chunk_size": self.chunk_size,
                "file_hash": file_hash,
                "hash_algorithm": "SHA256"
            }
        )
        response.raise_for_status()
        
        data = response.json()
        session_id = data["session_id"]
        total_parts = data["total_parts"]
        
        print(f"✓ Session initialized: {session_id}")
        print(f"  Total parts: {total_parts}")
        
        return session_id, total_parts
    
    def get_status(self, session_id: str) -> dict:
        """Get upload status."""
        response = requests.get(f"{self.api_url}/upload/{session_id}/status")
        response.raise_for_status()
        return response.json()
    
    def upload_part(self, session_id: str, part_number: int, chunk_data: bytes) -> bool:
        """Upload a single part with MD5 checksum."""
        try:
            # Calculate MD5 hash of part
            part_hash = hashlib.md5(chunk_data).hexdigest()
            
            response = requests.put(
                f"{self.api_url}/upload/{session_id}/part/{part_number}",
                files={"file": (f"part_{part_number}", chunk_data)},
                headers={"X-Part-Hash": part_hash}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"✗ Failed to upload part {part_number}: {e}")
            return False
    
    def complete_upload(self, session_id: str) -> dict:
        """Complete the upload and assemble file."""
        print("\nCompleting upload...")
        response = requests.post(f"{self.api_url}/upload/{session_id}/complete")
        response.raise_for_status()
        return response.json()
    
    def upload_file(self, file_path: str, session_id: Optional[str] = None) -> str:
        """
        Upload a file using multipart upload with checksums.
        
        If session_id is provided, resume from that session.
        Otherwise, start a new upload.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        file_size = file_path.stat().st_size
        filename = file_path.name
        
        # Calculate file hash if starting new upload
        file_hash = None
        if not session_id:
            print("Calculating file hash...")
            file_hash = self.calculate_file_hash(str(file_path))
            print(f"✓ File SHA256: {file_hash[:16]}...")
        
        # Start or resume session
        if session_id:
            print(f"Resuming upload session: {session_id}")
            status = self.get_status(session_id)
            total_parts = status["total_parts"]
            completed_parts = set(status["completed_parts"])
            print(f"Already completed: {len(completed_parts)}/{total_parts} parts")
        else:
            session_id, total_parts = self.init_upload(filename, file_size, file_hash)
            completed_parts = set()
        
        # Read file and split into chunks
        print(f"\nUploading {total_parts} parts using {self.max_workers} parallel workers...")
        start_time = time.time()
        
        with open(file_path, "rb") as f:
            # Create list of parts to upload
            parts_to_upload = []
            for part_num in range(1, total_parts + 1):
                if part_num in completed_parts:
                    continue  # Skip already uploaded parts
                
                f.seek((part_num - 1) * self.chunk_size)
                chunk_data = f.read(self.chunk_size)
                parts_to_upload.append((part_num, chunk_data))
        
        # Upload parts in parallel
        successful_uploads = 0
        failed_uploads = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.upload_part, session_id, part_num, chunk_data): part_num
                for part_num, chunk_data in parts_to_upload
            }
            
            for future in as_completed(futures):
                part_num = futures[future]
                try:
                    success = future.result()
                    if success:
                        successful_uploads += 1
                        progress = (len(completed_parts) + successful_uploads) / total_parts * 100
                        print(f"  ✓ Part {part_num}/{total_parts} uploaded ({progress:.1f}%)")
                    else:
                        failed_uploads += 1
                except Exception as e:
                    print(f"  ✗ Part {part_num} failed: {e}")
                    failed_uploads += 1
        
        upload_time = time.time() - start_time
        
        if failed_uploads > 0:
            print(f"\n⚠ Upload incomplete: {failed_uploads} parts failed")
            print(f"  Resume with: python client/uploader.py {file_path} --resume {session_id}")
            return session_id
        
        # Complete upload
        result = self.complete_upload(session_id)
        
        print(f"\n✓ Upload completed successfully!")
        print(f"  File: {result['file_path']}")
        print(f"  Time: {upload_time:.2f} seconds")
        print(f"  Speed: {file_size / upload_time / (1024*1024):.2f} MB/s")
        
        return session_id


def main():
    """CLI for multipart uploader."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  New upload:    python uploader.py <file_path>")
        print("  Resume upload: python uploader.py <file_path> --resume <session_id>")
        sys.exit(1)
    
    file_path = sys.argv[1]
    session_id = None
    
    if "--resume" in sys.argv:
        resume_idx = sys.argv.index("--resume")
        if len(sys.argv) > resume_idx + 1:
            session_id = sys.argv[resume_idx + 1]
    
    uploader = MultipartUploader()
    
    try:
        uploader.upload_file(file_path, session_id=session_id)
    except Exception as e:
        print(f"\n✗ Upload failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
