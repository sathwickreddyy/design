"""
Initialize database tables
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from src.core.config import settings
from src.models.database import Base


async def init_db():
    """Create all tables in database"""
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=True
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("✅ Database tables created successfully")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())
