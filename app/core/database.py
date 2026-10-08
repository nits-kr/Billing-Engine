from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# 1. Async Database Engine with Connection Pooling
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True
)

# 2. Asynchronous Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 3. Base class for all Declarative Database Models
Base = declarative_base()

# 4. FastAPI Dependency for database session management
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
