import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import get_settings

settings = get_settings()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

database_url = settings.database_url
if sys.platform == "win32" and database_url.startswith("postgresql+psycopg://"):
    # psycopg async can fail under Windows event loop modes depending on runtime startup path.
    # asyncpg is robust for this environment.
    database_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

engine = create_async_engine(database_url, future=True, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

