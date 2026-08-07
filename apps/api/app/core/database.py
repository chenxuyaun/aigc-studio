from collections.abc import AsyncGenerator

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# pool_pre_ping：丢弃被 MySQL wait_timeout / 网络抖动掐断的连接，避免 ready 偶发 2013
# pool_recycle：小于默认 wait_timeout(28800)，主动轮换长连接
# SQL echo 只在本机调试开：会把用户 prompt 等参数全量写日志，生产必须关
_engine_kwargs: dict[str, object] = {
    "echo": settings.APP_DEBUG and settings.APP_ENV != "production",
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
# sqlite 不支持连接池参数；生产 MySQL 再开连接数限制
if not settings.sqlalchemy_database_url.startswith("sqlite"):
    _engine_kwargs.update(
        {
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
        }
    )

engine = create_async_engine(settings.sqlalchemy_database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
