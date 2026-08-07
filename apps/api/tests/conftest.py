"""测试基建：独立内存 SQLite，绝不触碰真实开发库。

历史教训：曾直接复用全局 engine，跑全套测试时 drop_all 清空了
真实 aigc_studio.db（provider 配置、任务、素材全丢）。现在：
- 测试用独立内存库（StaticPool 共享连接）
- get_db 依赖与各模块引用的 AsyncSessionLocal 全部替换为测试会话
- 限流与 SQL echo 关闭
"""

import app.models
import pytest
import pytest_asyncio
from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from seed_data import seed
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# 独立内存库：StaticPool 让所有连接共享同一份数据
_test_engine = create_async_engine(
    "sqlite+aiosqlite://",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


# 后台任务/健康检查/种子数据等直接引用 AsyncSessionLocal 的模块也走测试库
def _install_test_sessions() -> None:
    import app.api.v1.health as health_mod
    import app.api.v1.tasks as tasks_mod
    import app.services.call_logger as call_logger_mod
    import app.services.task_runner as task_runner_mod
    import app.tasks.story_tasks as story_tasks_mod
    import seed_data as seed_mod

    for mod in (
        health_mod,
        tasks_mod,
        call_logger_mod,
        task_runner_mod,
        story_tasks_mod,
        seed_mod,
    ):
        mod.AsyncSessionLocal = TestingSessionLocal  # type: ignore[attr-defined]
    # seed 的 init_db 会操作全局真实库：测试库已 create_all，替换为空操作
    async def _noop_init_db() -> None:
        return None

    seed_mod.init_db = _noop_init_db  # type: ignore[attr-defined]


@pytest_asyncio.fixture
async def client():
    # 测试环境禁用限流与 SQL echo，避免整套用例互相 429 / 日志刷屏
    settings.RATE_LIMIT_PER_MINUTE = 0
    settings.RATE_LIMIT_LOGIN_PER_MINUTE = 0
    settings.APP_DEBUG = False
    # 测试环境强制进程内任务调度（.env 可能已开 USE_CELERY_WORKER=1，
    # 测试库无 redis，send_task 会连容器名失败拖垮用例）
    settings.USE_CELERY_WORKER = 0
    from app.core import rate_limit

    rate_limit._hits.clear()

    _install_test_sessions()
    app.dependency_overrides[get_db] = override_get_db

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    # 取消残留的后台任务：进程内调度（media/story）的 asyncio 任务若在
    # 下一个测试 drop_all 后仍在写库，会造成跨测试数据污染/404 时序失败。

    from app.services import task_runner as _tr
    from app.tasks import story_tasks as _st

    for mod in (_tr, _st):
        for task in list(getattr(mod, "_running", set())):
            task.cancel()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def _fake_text_resolver(monkeypatch: pytest.MonkeyPatch):
    """测试隔离：生产已移除 mock，所有文本 Provider 解析统一走离线 mock。

    只 patch 各使用模块的模块级绑定（from ... import resolve_text_provider），
    生产 resolver 的真实逻辑仍由 test_provider_resolver 直接验证。
    """
    from app.providers.mock.mock_text import MockTextProvider
    from app.services.provider_resolver import ResolvedTextProvider

    async def _fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            MockTextProvider(), "mock", False, provider_config_id=None, source="mock"
        )

    import app.api.v1.generations.text as _text_mod
    import app.api.v1.knowledge as _knowledge_mod
    import app.api.v1.story as _story_mod
    import app.api.v1.workflows as _workflows_mod
    import app.services.agent_chat as _agent_chat_mod
    import app.services.roleplay as _roleplay_mod
    import app.services.story_crew as _story_crew_mod
    import app.services.story_forge as _story_forge_mod

    for _mod in (
        _text_mod,
        _knowledge_mod,
        _story_mod,
        _workflows_mod,
        _agent_chat_mod,
        _roleplay_mod,
        _story_crew_mod,
        _story_forge_mod,
    ):
        monkeypatch.setattr(_mod, "resolve_text_provider", _fake_resolver)
    yield


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None


@pytest_asyncio.fixture
async def user_token(client: AsyncClient):
    """普通用户 token：测试库直接插一个 user1 再登录（验证数据隔离用）。"""
    from app.core.security import hash_password
    from app.models.user import User

    async with TestingSessionLocal() as session:
        session.add(
            User(
                username="user1",
                email="user1@test.local",
                password_hash=hash_password("user123"),
                role="user",
            )
        )
        await session.commit()
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "user1", "password": "user123"}
    )
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None
