"""
Database models for Google Drive-like system (Alex Xu production schema)

Complete schema includes:
- User management (profiles, quotas, authentication)
- Multi-device synchronization (track sync state per device)
- Workspaces (team collaboration, shared folders)
- Hierarchical file system (parent-child relationships)
- Version history (audit trail, rollback)
- Block-level storage (differential sync for large files)

Relationships:
- User 1:N Devices (one user has many devices)
- User 1:N Workspaces (one user owns many workspaces)
- User N:N Workspaces (many users can access many workspaces via workspace_members)
- Workspace 1:N Files (one workspace contains many files)
- File 1:N File (self-referencing parent-child hierarchy)
- File 1:N FileVersions (one file has many versions)
- FileVersion 1:N FileBlocks (one version split into many blocks)
"""
import hashlib
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


# ==========================================
# 1. USER MANAGEMENT
# ==========================================

class User(Base):
    """
    User accounts with authentication and storage quotas.
    
    Design:
    - UUID for distributed ID generation
    - Email as unique identifier
    - Storage quotas enforced (default 15GB free tier)
    - Track storage usage for billing
    
    Relationships:
    - 1:N with Device (one user has many devices)
    - 1:N with Workspace (one user owns many workspaces)
    - N:N with Workspace via WorkspaceMember (can access shared workspaces)
    """
    __tablename__ = "users"
    
    user_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="Primary key - distributed UUID generation"
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Unique email for authentication"
    )
    username: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Display name"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Bcrypt/Argon2 hashed password"
    )
    
    # Storage quotas
    storage_quota_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=15_000_000_000,  # 15GB
        nullable=False,
        comment="Storage limit (15GB free, upgradable)"
    )
    storage_used_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
        comment="Current storage usage (updated on upload/delete)"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="Last successful login timestamp"
    )
    
    def __repr__(self):
        return f"<User {self.username} ({self.email}) quota={self.storage_quota_bytes // (1024**3)}GB>"


# ==========================================
# 2. DEVICE TRACKING (Multi-device sync)
# ==========================================

class Device(Base):
    """
    Track user's devices for multi-device synchronization.
    
    Design:
    - Each client (phone, laptop, web) gets a device record
    - sync_cursor tracks last synchronized version
    - Enables incremental sync (only send changes since last sync)
    
    Relationships:
    - N:1 with User (FK: user_id → users.user_id)
    - 1:N with FileVersion (device creates versions)
    
    Example:
      user_id=u123 has devices:
        - device_id=d1 (iPhone), sync_cursor=1500
        - device_id=d2 (MacBook), sync_cursor=1498
        - device_id=d3 (Web), sync_cursor=1500
    """
    __tablename__ = "devices"
    
    device_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('users.user_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → users (device belongs to user)"
    )
    device_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="User-friendly name (e.g., 'John's iPhone')"
    )
    device_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type: 'mobile', 'desktop', 'web'"
    )
    os_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="OS details (e.g., 'iOS 17', 'macOS 14')"
    )
    
    # Sync state
    last_logged_in_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    sync_cursor: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
        comment="Last synced version_id (for incremental sync)"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="False if device logged out"
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    def __repr__(self):
        return f"<Device {self.device_name} ({self.device_type}) cursor={self.sync_cursor}>"


# ==========================================
# 3. WORKSPACES (Team collaboration)
# ==========================================

class Workspace(Base):
    """
    Workspaces for organizing files (personal or shared).
    
    Design:
    - Each user has a personal workspace ("My Drive")
    - Shared workspaces enable team collaboration
    - Storage quota can be set per workspace (team plans)
    
    Relationships:
    - N:1 with User (FK: owner_id → users.user_id)
    - 1:N with File (workspace contains files)
    - N:N with User via WorkspaceMember (shared access)
    
    Example:
      workspace_id=w1: "John's Drive" (owner=u123, is_shared=False)
      workspace_id=w2: "Marketing Team" (owner=u123, is_shared=True)
    """
    __tablename__ = "workspaces"
    
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4())
    )
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('users.user_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → users (workspace owner)"
    )
    workspace_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Display name (e.g., 'My Drive', 'Team Docs')"
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True for team workspaces, False for personal"
    )
    storage_quota_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Team storage quota (NULL = use owner's quota)"
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    def __repr__(self):
        shared = "shared" if self.is_shared else "personal"
        return f"<Workspace '{self.workspace_name}' ({shared})>"


class WorkspaceMember(Base):
    """
    Junction table for Workspace ↔ User many-to-many relationship.
    
    Design:
    - Enables sharing workspaces with multiple users
    - Role-based access control (owner, editor, viewer)
    - Composite primary key (workspace_id, user_id)
    
    Relationships:
    - N:1 with Workspace (FK: workspace_id)
    - N:1 with User (FK: user_id)
    
    Example:
      Workspace "Marketing Team" has members:
        - (w2, u123, 'owner')   - John (creator)
        - (w2, u456, 'editor')  - Sarah (can edit)
        - (w2, u789, 'viewer')  - Mike (read-only)
    """
    __tablename__ = "workspace_members"
    
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('workspaces.workspace_id', ondelete='CASCADE'),
        primary_key=True,
        comment="FK → workspaces"
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('users.user_id', ondelete='CASCADE'),
        primary_key=True,
        comment="FK → users"
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Access level: 'owner', 'editor', 'viewer'"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    def __repr__(self):
        return f"<WorkspaceMember workspace={self.workspace_id} user={self.user_id} role={self.role}>"


# ==========================================
# 4. FILES (Hierarchical + Workspace)
# ==========================================
# ==========================================
# 4. FILES (Hierarchical + Workspace)
# ==========================================

class FileRecord(Base):
    """
    Hierarchical file/folder metadata with workspace isolation.
    
    Design:
    - Folders and files in same table (distinguished by is_folder flag)
    - Parent-child relationships via parent_id (self-referencing FK)
    - Workspace isolation for multi-user/team access
    - Content-addressed storage: content_hash serves as storage key
    - Denormalized relative_path for fast lookups (avoids recursive queries)
    - Soft delete with is_deleted flag
    
    Relationships:
    - N:1 with Workspace (FK: workspace_id → workspaces.workspace_id)
    - N:1 with File (FK: parent_id → files.file_id) [self-referencing]
    - N:1 with User (FK: created_by → users.user_id)
    - 1:N with FileVersion (file has many versions)
    
    Example hierarchy:
      workspace_id=w1:
        id=f1: "My Drive" (parent_id=NULL, is_folder=TRUE, path="/")
        id=f2: "Documents" (parent_id=f1, is_folder=TRUE, path="/Documents")
        id=f3: "report.txt" (parent_id=f2, is_folder=FALSE, path="/Documents/report.txt")
    """
    __tablename__ = "files"
    
    # Primary key
    file_id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4()),
        comment="UUID for distributed generation"
    )
    
    # Workspace isolation
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('workspaces.workspace_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → workspaces (file belongs to workspace)"
    )
    
    # File metadata
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="File or folder name"
    )
    relative_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="Denormalized full path for fast lookups (e.g., '/Documents/report.txt')"
    )
    
    # Hierarchy
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), 
        ForeignKey('files.file_id', ondelete='CASCADE'),
        nullable=True,
        index=True,
        comment="FK → files (self-referencing parent-child)"
    )
    is_folder: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="TRUE for folders, FALSE for files"
    )
    
    # Version pointer (denormalized for fast access to current state)
    latest_version_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        nullable=True,
        comment="FK → file_versions (points to current version)"
    )
    
    # Content-addressed storage (files only, null for folders)
    checksum: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="SHA-256 hash of current content (enables deduplication)"
    )
    size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        comment="File size in bytes (NULL for folders)"
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="MIME type (e.g., 'application/pdf')"
    )
    
    # Ownership and timestamps
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('users.user_id', ondelete='SET NULL'),
        nullable=False,
        index=True,
        comment="FK → users (file creator)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    last_modified: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow,
        nullable=False,
        comment="Last modification timestamp"
    )
    
    # Soft delete (trash functionality)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Soft delete flag (move to trash)"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="When file was moved to trash"
    )
    
    # Composite indexes for performance
    __table_args__ = (
        Index('idx_workspace_path', 'workspace_id', 'relative_path'),  # Fast path lookup
        Index('idx_parent_folder', 'parent_id', 'is_folder'),  # Fast folder listing
        Index('idx_parent_name', 'parent_id', 'file_name'),  # Fast name lookup
        Index('idx_workspace_deleted', 'workspace_id', 'is_deleted'),  # Filter deleted files
    )
    
    @property
    def storage_key(self) -> Optional[str]:
        """
        Generate bucketed storage key for S3/MinIO (industry best practice).
        
        Format: v1/contents/{hash[0:2]}/{hash[2:4]}/{hash}
        Example: v1/contents/a3/f7/a3f7c2e9d8b1c7f2...
        
        Benefits:
        - Distributes objects across 65,536 prefixes (256*256)
        - Avoids S3 hot partition problems
        - Follows AWS/GCS best practices
        """
        if self.checksum:
            return f"v1/contents/{self.checksum[:2]}/{self.checksum[2:4]}/{self.checksum}"
        return None
    
    def __repr__(self):
        folder_marker = "📁" if self.is_folder else "📄"
        return f"<FileRecord {folder_marker} '{self.file_name}' path={self.relative_path}>"


# ==========================================
# 5. FILE VERSIONS (Device-aware)
# ==========================================
# ==========================================
# 5. FILE VERSIONS (Device-aware)
# ==========================================

class FileVersionHistory(Base):
    """
    Audit trail for all file versions with device tracking.
    
    Design:
    - Tracks every version of every file for rollback and audit
    - Device-aware (know which device created each version)
    - Enables conflict resolution (concurrent edits from different devices)
    - Snapshot of file metadata at each version
    
    Relationships:
    - N:1 with FileRecord (FK: file_id → files.file_id)
    - N:1 with Device (FK: device_id → devices.device_id)
    - N:1 with User (FK: user_id → users.user_id)
    - 1:N with FileBlock (version split into blocks)
    
    Example:
      file_id=f3 ("report.pdf") has versions:
        - v1: device=d1 (iPhone), size=1MB, checksum=abc123
        - v2: device=d2 (MacBook), size=1.2MB, checksum=def456
        - v3: device=d1 (iPhone), size=1.3MB, checksum=ghi789
    """
    __tablename__ = "file_versions"
    
    version_id: Mapped[str] = mapped_column(
        String(36), 
        primary_key=True, 
        default=lambda: str(uuid4()),
        comment="UUID for version identifier"
    )
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('files.file_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → files (which file this version belongs to)"
    )
    device_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey('devices.device_id', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment="FK → devices (which device created this version)"
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('users.user_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → users (who created this version)"
    )
    
    # Version snapshot
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Monotonically increasing version (1, 2, 3...)"
    )
    checksum: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 hash of content at this version"
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="File size at this version"
    )
    mime_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="MIME type at this version"
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="When this version was created"
    )
    
    # Composite indexes
    __table_args__ = (
        Index('idx_file_version', 'file_id', 'version_number'),  # Fast version lookup
        Index('idx_file_created', 'file_id', 'created_at'),  # Chronological queries
    )
    
    @property
    def storage_key(self) -> str:
        """Generate bucketed storage key (same as FileRecord)"""
        return f"v1/contents/{self.checksum[:2]}/{self.checksum[2:4]}/{self.checksum}"
    
    def __repr__(self):
        return f"<FileVersionHistory file={self.file_id} v{self.version_number} device={self.device_id}>"


# ==========================================
# 6. FILE BLOCKS (Differential sync)
# ==========================================

class FileBlock(Base):
    """
    Block-level storage for large files (differential synchronization).
    
    Design:
    - Files > 50MB split into 4KB blocks
    - Only upload changed blocks (rsync-style sync)
    - Enables deduplication across versions (same block hash = reuse storage)
    - block_order defines sequence for reassembly
    
    Relationships:
    - N:1 with FileVersionHistory (FK: version_id → file_versions.version_id)
    
    Example:
      version_id=v3 (100MB file) has blocks:
        - block_id=b1, block_order=0, block_hash=abc123, size=4096, key=blocks/ab/c1/abc123
        - block_id=b2, block_order=1, block_hash=def456, size=4096, key=blocks/de/f4/def456
        - ...
        - block_id=b25600, block_order=25599, block_hash=xyz789, size=4096
    
    Block reassembly:
      1. Query: SELECT * FROM file_blocks WHERE version_id=v3 ORDER BY block_order
      2. Download each block from MinIO/S3 using storage_key
      3. Concatenate blocks in order
      4. Verify final checksum matches file_versions.checksum
    """
    __tablename__ = "file_blocks"
    
    block_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="UUID for block identifier"
    )
    version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey('file_versions.version_id', ondelete='CASCADE'),
        nullable=False,
        index=True,
        comment="FK → file_versions (which version this block belongs to)"
    )
    block_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Position in file (0, 1, 2...) for reassembly"
    )
    block_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 hash of this block's content (for deduplication)"
    )
    block_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4096,
        comment="Block size in bytes (typically 4KB, last block may be smaller)"
    )
    storage_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="MinIO/S3 key for this block (e.g., blocks/ab/c1/abc123...)"
    )
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )
    
    # Composite indexes
    __table_args__ = (
        Index('idx_version_order', 'version_id', 'block_order'),  # Fast ordered retrieval
        Index('idx_block_hash', 'block_hash'),  # Deduplication lookup
    )
    
    @property
    def storage_key_bucketed(self) -> str:
        """Generate bucketed storage key for blocks"""
        return f"v1/blocks/{self.block_hash[:2]}/{self.block_hash[2:4]}/{self.block_hash}"
    
    def __repr__(self):
        return f"<FileBlock version={self.version_id} order={self.block_order} hash={self.block_hash[:8]}...>"
