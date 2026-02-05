"""
Sync Client Library
Handles file download, upload, and conflict resolution
"""

import hashlib
import logging
from typing import Optional, Dict
import httpx

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class SyncClient:
    """Client for syncing files with conflict detection"""
    
    def __init__(self, client_id: str, server_url: str = "http://localhost:8000"):
        self.client_id = client_id
        self.server_url = server_url
        self.logger = logging.getLogger(f"Client_{client_id}")
        
        # Local state: tracks file versions we know about
        self.local_files: Dict[str, dict] = {}
        
        self.logger.info(f"🟢 [{self.client_id}] Initialized (server: {server_url})")
    
    def _compute_hash(self, content: str) -> str:
        """Compute SHA256 hash"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def download(self, file_id: str) -> dict:
        """Download file from server and cache version"""
        self.logger.info(f"📥 [{self.client_id}] Downloading {file_id}...")
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(f"{self.server_url}/files/{file_id}")
                response.raise_for_status()
                
                data = response.json()
                
                # Cache locally
                self.local_files[file_id] = {
                    "content": data["content"],
                    "version": data["version"],
                    "hash": data["content_hash"]
                }
                
                self.logger.info(
                    f"✅ [{self.client_id}] Downloaded {file_id} v{data['version']}: "
                    f"\"{data['content'][:50]}{'...' if len(data['content']) > 50 else ''}\""
                )
                
                return data
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self.logger.warning(f"❌ [{self.client_id}] File {file_id} not found")
                raise
    
    def edit_file(self, file_id: str, new_content: str):
        """Edit file locally (simulates user editing)"""
        if file_id not in self.local_files:
            self.logger.error(f"❌ [{self.client_id}] Cannot edit {file_id}: not downloaded")
            raise ValueError(f"File {file_id} not in local cache. Download first.")
        
        old_content = self.local_files[file_id]["content"]
        self.local_files[file_id]["content"] = new_content
        self.local_files[file_id]["hash"] = self._compute_hash(new_content)
        
        self.logger.info(
            f"✏️ [{self.client_id}] Edited {file_id}:\n"
            f"   Old: \"{old_content}\"\n"
            f"   New: \"{new_content}\""
        )
    
    async def upload(self, file_id: str) -> dict:
        """
        Upload file to server with optimistic locking
        Returns conflict info if version mismatch
        """
        if file_id not in self.local_files:
            self.logger.error(f"❌ [{self.client_id}] Cannot upload {file_id}: not in cache")
            raise ValueError(f"File {file_id} not in local cache")
        
        local_file = self.local_files[file_id]
        expected_version = local_file["version"]
        content = local_file["content"]
        content_hash = local_file["hash"]
        
        self.logger.info(
            f"📤 [{self.client_id}] Uploading {file_id} "
            f"(expected_version={expected_version})..."
        )
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.server_url}/files/{file_id}",
                    json={
                        "content": content,
                        "expected_version": expected_version,
                        "content_hash": content_hash
                    },
                    timeout=10.0
                )
                
                if response.status_code == 409:
                    # CONFLICT!
                    conflict_data = response.json()
                    self.logger.warning(
                        f"⚠️ [{self.client_id}] CONFLICT detected for {file_id}!\n"
                        f"   Expected version: {expected_version}\n"
                        f"   Server version: {conflict_data['current_version']}\n"
                        f"   Server content: \"{conflict_data['server_content']}\"\n"
                        f"   Local content: \"{content}\""
                    )
                    return {
                        "status": "conflict",
                        "conflict_data": conflict_data
                    }
                
                response.raise_for_status()
                data = response.json()
                
                # Update local version
                self.local_files[file_id]["version"] = data["version"]
                
                self.logger.info(
                    f"✅ [{self.client_id}] Upload successful: "
                    f"{file_id} v{expected_version} → v{data['version']}"
                )
                
                return {"status": "success", "data": data}
                
            except httpx.HTTPStatusError as e:
                self.logger.error(f"❌ [{self.client_id}] Upload failed: {e}")
                raise
    
    async def resolve_conflict_keep_both(self, file_id: str, conflict_data: dict):
        """
        Conflict resolution strategy: Keep both versions
        Creates a conflicted copy for the losing client
        """
        self.logger.info(f"🔧 [{self.client_id}] Resolving conflict for {file_id}...")
        
        # Fetch latest server version
        server_content = conflict_data["server_content"]
        server_version = conflict_data["current_version"]
        local_content = self.local_files[file_id]["content"]
        
        # Create conflicted copy name
        conflicted_file_id = f"{file_id.rsplit('.', 1)[0]} (conflicted copy {self.client_id}).txt"
        
        self.logger.info(
            f"📝 [{self.client_id}] Conflict resolution strategy: KEEP BOTH\n"
            f"   Server version ({file_id}): \"{server_content}\" (v{server_version})\n"
            f"   Local version (saved as {conflicted_file_id}): \"{local_content}\""
        )
        
        # Update local cache with server version
        self.local_files[file_id] = {
            "content": server_content,
            "version": server_version,
            "hash": self._compute_hash(server_content)
        }
        
        # Store conflicted copy locally (in real system, would save to disk)
        self.local_files[conflicted_file_id] = {
            "content": local_content,
            "version": 0,  # New file
            "hash": self._compute_hash(local_content)
        }
        
        # Upload conflicted copy to server
        await self.upload(conflicted_file_id)
        
        self.logger.info(
            f"✅ [{self.client_id}] Conflict resolved:\n"
            f"   - {file_id}: accepted server version v{server_version}\n"
            f"   - {conflicted_file_id}: saved local changes"
        )
        
        return {
            "strategy": "keep_both",
            "server_file": file_id,
            "conflicted_file": conflicted_file_id
        }
    
    async def create_file(self, file_id: str, content: str):
        """Create a new file on the server"""
        self.logger.info(f"➕ [{self.client_id}] Creating new file {file_id}...")
        
        content_hash = self._compute_hash(content)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/files/{file_id}",
                json={
                    "content": content,
                    "expected_version": 0,  # New file
                    "content_hash": content_hash
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Cache locally
            self.local_files[file_id] = {
                "content": content,
                "version": data["version"],
                "hash": content_hash
            }
            
            self.logger.info(f"✅ [{self.client_id}] Created {file_id} v{data['version']}")
            return data
