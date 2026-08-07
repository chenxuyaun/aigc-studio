from __future__ import annotations

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

# apps/api 根目录：无论从 monorepo 根还是 apps/api 启动，SQLite 都指向同一文件。
_API_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _API_ROOT.parent.parent
_DEFAULT_SQLITE = (_API_ROOT / "aigc_studio.db").as_posix()


class Settings(BaseSettings):
    APP_ENV: str = "development"
    APP_NAME: str = "AIGC Studio"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "dev-secret-key"
    APP_BASE_URL: str = "http://localhost:5000"

    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DATABASE: str = "aigc_studio"
    MYSQL_USER: str = "aigc"
    MYSQL_PASSWORD: str = "changeme"
    MYSQL_ROOT_PASSWORD: str = "changeme"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # 角色陪伴多层记忆（MemoryCore gateway，standalone :8420）
    TDAI_MEMORY_ENDPOINT: str = "http://127.0.0.1:8420"
    TDAI_MEMORY_API_KEY: str = ""
    # 交互记忆注入预算（字符，超限截断）
    MEMORY_INJECT_MAX_CHARS: int = 2500

    JWT_SECRET_KEY: str = "dev-jwt-secret"
    JWT_ACCESS_TOKEN_MINUTES: int = 30
    JWT_REFRESH_TOKEN_DAYS: int = 14

    INITIAL_ADMIN_EMAIL: str = "admin@aigc.local"
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str = "admin123"

    STORAGE_PROVIDER: str = "local"
    # 默认落在 apps/api/storage，避免从 monorepo 根启动时写到仓库根目录
    STORAGE_LOCAL_PATH: str = str(_API_ROOT / "storage")
    STORAGE_ENDPOINT: str = ""
    STORAGE_ACCESS_KEY: str = ""
    STORAGE_SECRET_KEY: str = ""
    STORAGE_BUCKET: str = "aigc-studio"
    STORAGE_REGION: str = "auto"
    STORAGE_PUBLIC_BASE_URL: str = ""
    # 私有媒体预签名 GET 有效期（秒）；用户媒体禁止依赖 PUBLIC_BASE_URL
    STORAGE_SIGNED_GET_TTL_SECONDS: int = 300
    # 新写入走 R2 的用户百分比 0–100；0 表示全部 local（无 Token 可运行）
    STORAGE_R2_WRITE_PERCENT: int = 0

    DEFAULT_TEXT_PROVIDER: str = ""
    DEFAULT_IMAGE_PROVIDER: str = ""
    DEFAULT_VIDEO_PROVIDER: str = ""
    DEFAULT_SPEECH_PROVIDER: str = ""

    # grok2api 管理凭据（账号健康度监控用；仅存于 .env，勿提交）
    GROK2API_ADMIN_USERNAME: str = ""
    GROK2API_ADMIN_PASSWORD: str = ""

    OPENAI_COMPATIBLE_BASE_URL: str = ""
    OPENAI_COMPATIBLE_API_KEY: str = ""
    OPENAI_COMPATIBLE_MODEL: str = ""
    # 图像默认模型（grok2api 的 /images/generations 用）
    OPENAI_COMPATIBLE_IMAGE_MODEL: str = ""
    # 视频默认模型（grok2api 的 /videos/generations 用，模型恢复后生效）
    OPENAI_COMPATIBLE_VIDEO_MODEL: str = ""
    # 同一上游的最小请求间隔（秒，0=关闭）：防密集请求触发上游风控（如 Grok anti-bot）
    OPENAI_COMPATIBLE_MIN_INTERVAL: float = 1.5

    # HuggingFace 免费推理 API（无需 Key 即可使用，有速率限制）
    HUGGINGFACE_TOKEN: str = ""
    DEFAULT_TEXT_PROVIDER_REAL: str = "huggingface"
    DEFAULT_IMAGE_PROVIDER_REAL: str = "huggingface"
    DEFAULT_SPEECH_PROVIDER_REAL: str = "huggingface"

    CORS_ALLOWED_ORIGINS: str = "http://localhost:5000"
    LOG_LEVEL: str = "INFO"

    MOCK_PROVIDER_DELAY_MIN_MS: int = 300
    MOCK_PROVIDER_DELAY_MAX_MS: int = 2000
    MOCK_PROVIDER_FAILURE_RATE: int = 0

    # 0 = 进程内 asyncio（默认）；1 = 投递 Celery（需 worker 在线）
    USE_CELERY_WORKER: int = 0

    # 简易内存限流：每 IP 每分钟最大请求数（0=关闭）
    RATE_LIMIT_PER_MINUTE: int = 120
    # 登录接口更严
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 20
    # 部署在受信反向代理之后才置 true（否则信任 XFF 可被客户端伪造绕过限流）
    TRUST_PROXY: bool = False
    # 每用户素材总配额（字节；0=不限）
    USER_STORAGE_QUOTA_BYTES: int = 0

    DATABASE_URL: str = ""

    model_config = {
        # 同时尝试 monorepo 根与 apps/api，避免 CWD 不同读不到 .env
        "env_file": (str(_REPO_ROOT / ".env"), str(_API_ROOT / ".env"), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _resolve_relative_paths(self) -> Settings:
        # .env 里常写 ./storage；统一锚定到 apps/api，避免写到仓库根。
        p = Path(self.STORAGE_LOCAL_PATH)
        if not p.is_absolute():
            self.STORAGE_LOCAL_PATH = str((_API_ROOT / p).resolve())
        return self

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> Settings:
        """生产环境拒绝默认/占位符密钥，防止用公开默认值伪造 JWT 或解密 Provider Key。"""
        if self.APP_ENV != "production":
            return self
        defaults = {
            "APP_SECRET_KEY": ("dev-secret-key", "APP_SECRET_KEY"),
            "JWT_SECRET_KEY": ("dev-jwt-secret", "JWT_SECRET_KEY"),
            "INITIAL_ADMIN_PASSWORD": ("admin123", "INITIAL_ADMIN_PASSWORD"),
        }
        for env_value, env_name in defaults.values():
            if self.model_dump().get(env_name) == env_value:
                raise ValueError(
                    f"生产环境禁止使用默认 {env_name}，请在 .env 配置强随机值"
                )
        if "change-me" in (self.JWT_SECRET_KEY + self.APP_SECRET_KEY):
            raise ValueError("生产环境 JWT/APP secret 不能包含占位符 change-me")
        return self

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            url = self.DATABASE_URL
            # 相对 sqlite 路径也锚定到 apps/api
            if url.startswith("sqlite") and ":///" in url:
                prefix, path = url.split(":///", 1)
                if path and not Path(path).is_absolute():
                    return f"{prefix}:///{(_API_ROOT / path).resolve().as_posix()}"
            return url
        # 三斜杠 + 绝对路径：sqlite+aiosqlite:///D:/.../aigc_studio.db
        return f"sqlite+aiosqlite:///{_DEFAULT_SQLITE}"


settings = Settings()
