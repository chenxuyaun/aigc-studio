from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.core.config import settings
from app.core.rate_limit import check_rate_limit

# 结构化日志：生产输出 JSON 行（便于 journal/采集），开发保持可读
if settings.APP_ENV == "production":
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
    )

logger = structlog.get_logger()

# 健康检查与静态探测不计入全局限流
_RATE_LIMIT_SKIP_PREFIXES = (
    "/healthz",
    "/api/v1/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

# 已鉴权的私有媒体读路径：缩略图网格会短时打出大量 access-url/content，
# 若与业务 API 共用 120/min 全局桶，素材页必然 429。单独放宽。
_MEDIA_READ_MARKERS = (
    "/access-url",
    "/content",
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # 数据库结构由 Alembic 迁移管理（部署时执行 `alembic upgrade head`）。
    # 本地开发首次运行需先执行迁移；测试通过 seed() 自建 schema。
    logger.info(
        "app_started",
        env=settings.APP_ENV,
        storage=settings.STORAGE_PROVIDER,
        r2_write_percent=settings.STORAGE_R2_WRITE_PERCENT,
        use_celery=bool(settings.USE_CELERY_WORKER),
    )
    # 进程崩溃恢复：把遗留的 processing/queued 任务标记失败，避免永久卡死
    try:
        from app.services.task_runner import _recover_stale_tasks

        await _recover_stale_tasks()
    except Exception:
        logger.warning("stale_task_recovery_failed", exc_info=True)
    # MCP session manager 需要 lifespan 初始化（task group），否则 /mcp 请求 500
    try:
        from app.mcp.server import mcp

        async with mcp.session_manager.run():
            yield
            return
    except Exception:
        logger.warning("mcp_session_start_failed", exc_info=True)
    yield
    logger.info("app_stopped")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.APP_DEBUG else None,
    redoc_url="/redoc" if settings.APP_DEBUG else None,
    openapi_url="/openapi.json" if settings.APP_DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_body(
    code: str, message: str, request_id: str, details: object = None
) -> dict[str, object]:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details},
        "request_id": request_id,
    }


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    # X-Request-ID：仅接受客户端合法格式（36 位 UUID 或 ≤64 字符的字母数字连字符），
    # 防止用任意长/控制字符污染日志与响应头
    raw_rid = request.headers.get("X-Request-ID", "")
    if raw_rid and len(raw_rid) <= 64 and all(
        c.isalnum() or c in "-_" for c in raw_rid
    ):
        request_id = raw_rid
    else:
        request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    path = request.url.path
    if not any(path.startswith(p) for p in _RATE_LIMIT_SKIP_PREFIXES):
        try:
            # 媒体读路径用独立高配额桶，避免拖垮列表/登录等业务接口。
            if any(m in path for m in _MEDIA_READ_MARKERS):
                check_rate_limit(request, limit=600, bucket="media-read")
            else:
                check_rate_limit(request)
        except HTTPException as exc:
            # 尽量告知剩余等待秒数，前端退避用；缺省 5s 避免全员 60s 雪崩重试。
            retry_after = str(exc.headers.get("Retry-After", "5")) if exc.headers else "5"
            return JSONResponse(
                status_code=exc.status_code,
                content=_error_body("RATE_LIMITED", str(exc.detail), request_id),
                headers={"Retry-After": retry_after},
            )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled_error", request_id=request_id, path=path)
        return JSONResponse(
            status_code=500,
            content=_error_body("INTERNAL_ERROR", "服务器内部错误", request_id),
        )
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        429: "RATE_LIMITED",
    }.get(exc.status_code, "ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, str(exc.detail), request_id),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    # 只回传字段/规则摘要，不回显 input 原始值（可能含密码/密钥）
    details = [
        {"loc": list(e.get("loc") or []), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_error_body("VALIDATION_ERROR", "请求参数校验失败", request_id, details),
    )


app.include_router(v1_router)

# OpenAI 兼容网关（SillyTavern 等客户端用，路径 /v1/chat/completions）
from app.api.v1.openai_gateway import router as openai_gateway_router  # noqa: E402

app.include_router(openai_gateway_router)


# MCP：streamable HTTP 端点（/mcp），外层 Bearer JWT 校验
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class _MCPAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            auth = request.headers.get("authorization", "")
            if not auth.lower().startswith("bearer "):
                return JSONResponse({"detail": "MCP 需要 Bearer token"}, status_code=401)
            token = auth.split(" ", 1)[1]
            from app.core.security import verify_token

            payload = verify_token(token)
            if not payload or payload.get("type") != "access":
                return JSONResponse({"detail": "token 无效"}, status_code=401)
        return await call_next(request)


app.add_middleware(_MCPAuthMiddleware)

from app.mcp.server import mcp  # noqa: E402

app.mount("/mcp", mcp.streamable_http_app())


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
