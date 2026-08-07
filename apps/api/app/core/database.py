import os
from collections.abc import AsyncGenerator

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

# pool_pre_ping：丢弃被 MySQL wait_timeout / 网络抖动掐断的连接，避免 ready 偶发 2013
# pool_recycle：小于默认 wait_timeout(28800)，主动轮换长连接
# SQL echo 由 DB_ECHO 独立控制（默认关：会把用户 prompt 等参数全量写日志）；
# 不要挂在 APP_DEBUG 上——那会连 Swagger /docs 一起关掉
_engine_kwargs: dict[str, object] = {
    "echo": settings.DB_ECHO and settings.APP_ENV != "production",
    "pool_pre_ping": True,
    "pool_recycle": 1800,
}
# celery worker 以 asyncio.run 跑任务，每任务一个新事件循环：常驻连接池会把
# 旧 loop 的 aiomysql 连接带到下次任务，dispose 时在已关闭 loop 上 call_soon，
# 刷 "RuntimeError: Event loop is closed" 噪音。worker 用 NullPool 现连现关
# （连接随 session 在任务自己的 loop 内关闭），API 进程保持默认连接池。
if os.environ.get("DB_POOL_CLASS", "").lower() == "null":
    _engine_kwargs["poolclass"] = NullPool
elif not settings.sqlalchemy_database_url.startswith("sqlite"):
    # sqlite 不支持连接池参数；生产 MySQL 再开连接数限制
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
