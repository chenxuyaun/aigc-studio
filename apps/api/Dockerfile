# 与 pyproject requires-python >=3.14 对齐：3.12 会立即求值类内自引用注解（PEP 649 仅 3.14+ 默认开启）
FROM python:3.14-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libjpeg62-turbo-dev zlib1g-dev \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# 与 pyproject 对齐的运行时依赖（镜像内用 pip；本地/线上 systemd 用 uv/venv）
# 使用清华镜像源：pypi.org 在国内网络下 SSL 连接不稳定会导致 build 失败
COPY apps/api/pyproject.toml .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "fastapi>=0.118.0" \
    "uvicorn[standard]>=0.34.0" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "aiomysql>=0.2.0" \
    "aiosqlite>=0.20.0" \
    "greenlet>=3.1.0" \
    "alembic>=1.14.0" \
    "celery[redis]>=5.4.0" \
    "redis>=5.2.0" \
    "pydantic>=2.10.0" \
    "pydantic-settings>=2.6.0" \
    "python-jose[cryptography]>=3.3.0" \
    "argon2-cffi>=23.1.0" \
    "httpx>=0.28.0" \
    "structlog>=24.4.0" \
    "python-multipart>=0.0.12" \
    "aiofiles>=24.1.0" \
    "pillow>=11.0.0" \
    "boto3>=1.35.0" \
    "edge-tts>=7.0.0" \
    "PyMySQL>=1.1.0" \
    "mcp>=1.2.0,<2.0"

COPY apps/api/ .
COPY apps/api/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# compose 环境用 entrypoint 自动 migrate+seed 后启动；直接运行 CMD 时跳过（部署脚本负责）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
