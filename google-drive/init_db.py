"""
Initialize database tables for Google Drive-like system.

Creates all tables in the following order (handled by SQLAlchemy):
1. users (base table)
2. devices (depends on users)
3. workspaces (depends on users)
4. workspace_members (depends on users + workspaces)
5. files (depends on workspaces + users)
6. file_versions (depends on files + devices + users)
7. file_blocks (depends on file_versions)

Foreign key dependencies are automatically resolved by SQLAlchemy.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import settings
from src.models.database import Base, User, Device, Workspace, WorkspaceMember, FileRecord, FileVersionHistory, FileBlock


async def init_db():
    """Create all tables in database"""
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=True  # Show SQL statements
    )
    
    print("🔧 Initializing database with production schema...")
    print(f"📍 Database URL: {settings.DATABASE_URL.split('@')[1] if '@' in settings.DATABASE_URL else 'localhost'}")
    print()
    
    async with engine.begin() as conn:
        # Drop all tables (useful for development, comment out for production)
        # await conn.run_sync(Base.metadata.drop_all)
        # print("🗑️  Dropped existing tables")
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    print()
    print("✅ Database tables created successfully!")
    print()
    print("📊 Created tables:")
    print("   1. users              - User accounts with quotas")
    print("   2. devices            - Multi-device sync tracking")
    print("   3. workspaces         - Personal/shared workspaces")
    print("   4. workspace_members  - Workspace access control")
    print("   5. files              - Hierarchical file system")
    print("   6. file_versions      - Version history with device tracking")
    print("   7. file_blocks        - Block-level storage for large files")
    print()
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())
