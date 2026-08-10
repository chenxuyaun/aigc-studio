"""进程内媒体任务执行器。

支持双模式：
- Mock 模式（默认）：用 asyncio 后台任务模拟异步媒体生成
- 真实模式：通过 ProviderRegistry 调用 HuggingFace 等真实 AI API

当 task.model != "mock" 且存在对应真实 Provider 时，走真实生成；
真实 Provider 失败时自动回退 Mock，保证演示不中断。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.generation_task import GenerationTask
from app.providers.mock import media
from app.providers.registry import ProviderRegistry
from app.services.call_logger import log_call
from app.services.media_access import sign_content_url
from app.storage import choose_write_backend, get_storage

logger = structlog.get_logger()

# 保留后台任务引用，避免被 GC 回收。
_running: set[asyncio.Task[None]] = set()

_PROGRESS_STEPS = (10, 35, 60, 85)
_EXT_MIME = {"svg": "image/svg+xml", "wav": "audio/wav"}


def schedule_media_task(task_id: str) -> None:
    """从请求处理器调度一个媒体任务的后台处理。"""
    task = asyncio.create_task(run_media_task(task_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _delay() -> None:
    await asyncio.sleep(max(settings.MOCK_PROVIDER_DELAY_MIN_MS, 50) / 1000)


async def _is_cancelled(db: AsyncSession, task_id: str) -> bool:
    """从 DB 重读任务状态，用于长 await 之后检查取消（防止覆盖终态）。"""
    try:
        row = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        return row is None or row.status == "cancelled"
    except Exception:
        return False


async def _recover_stale_tasks(max_age_seconds: int = 1800) -> None:
    """启动扫描：把进程崩溃遗留的 processing/queued 任务标记为失败，避免永久卡死。"""
    from datetime import UTC as _UTC
    from datetime import datetime, timedelta

    cutoff = datetime.now(_UTC) - timedelta(seconds=max_age_seconds)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(GenerationTask).where(
                    GenerationTask.status.in_(["queued", "processing", "submitting"]),
                    GenerationTask.updated_at < cutoff,
                )
            )
        ).scalars().all()
        for row in rows:
            row.status = "failed"
            row.error_message = "服务重启导致任务中断，请重新生成"
            row.completed_at = datetime.now(_UTC)
            logger.warning("stale_task_recovered", task_id=row.id, task_type=row.task_type)
        if rows:
            await db.commit()
            logger.info("recovered_stale_tasks", count=len(rows))


# 前端/配置里的 Provider 别名，不能当作上游模型 id 原样提交。
_PROVIDER_ALIASES = frozenset(
    {"mock", "huggingface", "openai_compatible", "grok", "grok2api"}
)


def _upstream_model_id(model: str) -> str:
    """别名 → 空串（用 Provider 默认模型）；具体 id（如 org/model）原样保留。"""
    raw = (model or "").strip()
    if not raw or raw.lower() in _PROVIDER_ALIASES:
        return ""
    return raw


async def _provider_settings(
    db: AsyncSession, model: str
) -> tuple[str, str, str] | None:
    """按 model（id / name 别名 / default_model）解析 DB ProviderConfig。

    返回 (base_url, api_key, default_model)；未配置返回 None（走 env 兜底）。
    图片/视频/语音的真实链路必须走 DB 配置——容器内 env 的
    OPENAI_COMPATIBLE_BASE_URL 指向 127.0.0.1 时会打到 API 自己。
    """
    from sqlalchemy import func, or_, select

    from app.models.provider_config import ProviderConfig
    from app.security.ownership import open_secret

    stmt = select(ProviderConfig).where(
        ProviderConfig.is_enabled.is_(True),
        or_(
            ProviderConfig.id == model,
            func.lower(ProviderConfig.name) == model.lower(),
            func.lower(ProviderConfig.name).contains(model.lower()),
            ProviderConfig.default_model == model,
        ),
    )
    row = (await db.execute(stmt.order_by(ProviderConfig.priority))).scalars().first()
    if row is None:
        return None
    return (
        (row.base_url or "").rstrip("/"),
        open_secret(row.encrypted_api_key or ""),
        row.default_model or "",
    )


def _provider_kwargs(
    settings_row: tuple[str, str, str] | None, *, include_default_model: bool = True
) -> dict[str, Any]:
    """组装 provider 构造参数。图片/视频分支不传 default_model：
    DB 的 default_model 是文本模型（grok-chat-fast），上游图片/视频端点
    需要各自的内置默认（grok-imagine-image / grok-imagine-video）。
    """
    if settings_row is None:
        return {}
    base_url, api_key, default_model = settings_row
    kwargs = {
        "base_url": base_url,
        "api_key": api_key or "none",
    }
    if include_default_model:
        kwargs["default_model"] = default_model
    return kwargs


async def _load_reference_image(
    db: AsyncSession, params: dict[str, object]
) -> tuple[str | None, str | None]:
    """读取参考图（写真 Photo 或素材 Asset）为 data URL，供上游 img2img 使用。

    返回 (data_url, 失败原因)。图大于 3MB 或读取失败时返回 (None, 原因)，
    不阻断主流程（继续走文生图）。
    """
    from app.models.asset import Asset
    from app.models.photo import Photo

    ref_id = str(params.get("reference_photo_id") or params.get("reference_asset_id") or "")
    if not ref_id:
        return None, None
    photo: Photo | None = await db.get(Photo, ref_id)
    ref: Photo | Asset | None = photo
    model_cls: type[Photo] | type[Asset] = Photo
    if ref is None:
        asset: Asset | None = await db.get(Asset, ref_id)
        if asset is not None:
            ref = asset
            model_cls = Asset
    if ref is None:
        return None, "参考图不存在"
    try:
        store = get_storage(getattr(ref, "storage_backend", None) or "local")
        data = await store.get(ref.storage_key)
        if len(data) > 3 * 1024 * 1024:
            return None, "参考图超过 3MB，跳过图生图"
        mime = getattr(ref, "mime_type", None) or "image/png"
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", None
    except Exception as exc:
        logger.warning(
            "reference_image_load_failed",
            model=model_cls.__name__,
            error=str(exc)[:120],
        )
        return None, f"参考图读取失败: {str(exc)[:100]}"


async def _download_media(url: str) -> tuple[bytes, str]:
    """统一媒体下载：data URL 直接解码；http(s) URL 下载后按 content-type 定 MIME。"""
    if url.startswith("data:"):
        header, b64 = url.split(",", 1)
        mime = header.split(":")[1].split(";")[0] if ":" in header else "application/octet-stream"
        return base64.b64decode(b64), mime
    import httpx

    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"媒体下载 {resp.status_code}: {resp.text[:120]}")
    ctype = (resp.headers.get("content-type") or "application/octet-stream").lower()
    return resp.content, ctype


def _ext_from_mime(mime: str, default: str) -> str:
    mime = mime.lower()
    if "png" in mime:
        return "png"
    if "jpeg" in mime or "jpg" in mime:
        return "jpg"
    if "webp" in mime:
        return "webp"
    if "gif" in mime:
        return "gif"
    if "flac" in mime:
        return "flac"
    if "wav" in mime or "wave" in mime:
        return "wav"
    if "mp4" in mime:
        return "mp4"
    if "webm" in mime:
        return "webm"
    return default


def _rewrite_media_url(url: str, upstream_base: str) -> str:
    """上游返回的 media URL 常指向其容器内 127.0.0.1/localhost。

    按 provider base_url（如 http://host.docker.internal:8000/v1）的 host
    改写，保证 AIGC 容器内也能下载到 grok2api 的媒体。
    """
    from urllib.parse import urlparse, urlunparse

    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        u = urlparse(url)
        if u.hostname not in ("127.0.0.1", "localhost"):
            return url
        p = urlparse(upstream_base)
        if not p.hostname:
            return url
        return urlunparse(
            (p.scheme or u.scheme, p.netloc, u.path, u.params, u.query, u.fragment)
        )
    except ValueError:
        return url


async def _try_real_media(
    task_type: str, prompt: str, params: dict[str, object], model: str, db: AsyncSession
) -> tuple[bytes, str, str] | tuple[None, str]:
    """尝试真实 Provider。

    成功: (bytes, mime, ext)
    失败: (None, reason) — reason 供 result.fallback_reason 展示。
    """
    upstream = _upstream_model_id(model)
    provider_conf = await _provider_settings(db, model)
    upstream_base = provider_conf[0] if provider_conf else ""
    try:
        if task_type == "image":
            # DB 配置优先：配置里的 base_url 就是 OpenAI 兼容网关（grok2api/cpa 等），
            # 直接走 OpenAICompatible，避免 model 名（显示名/配置 id）被 registry
            # 误路由到 HuggingFace；无配置时才用 registry 按关键字解析。
            image_provider: Any
            if provider_conf:
                from app.providers.openai_compatible import OpenAICompatibleImageProvider

                image_provider = OpenAICompatibleImageProvider(
                    **_provider_kwargs(provider_conf, include_default_model=False),
                )
            else:
                image_provider = ProviderRegistry.get_image_provider(
                    model,
                    **_provider_kwargs(None, include_default_model=False),
                )
            if image_provider.__class__.__name__ == "MockImageProvider":
                return None, "图像 Provider 解析为 Mock，未走真实路径"
            submit_params = dict(params)
            if params.get("reference_photo_id") or params.get("reference_asset_id"):
                ref_url, ref_err = await _load_reference_image(db, params)
                if ref_url:
                    submit_params["image"] = ref_url
                elif ref_err:
                    logger.warning("reference_skip", task_id=model, reason=ref_err)
            result = await image_provider.submit(prompt, model=upstream, **submit_params)
            poll_result = await image_provider.poll(str(result.get("task_id") or ""))
            if poll_result.get("status") != "succeeded":
                err = str(poll_result.get("error") or poll_result.get("status") or "unknown")
                return None, f"真实图像任务未成功: {err[:160]}"
            url = str(poll_result.get("image_url") or "")
            if not url:
                return None, "真实图像结果缺少图片地址"
            data, mime = await _download_media(_rewrite_media_url(url, upstream_base))
            return data, mime, _ext_from_mime(mime, "bin")
        if task_type == "video":
            # 与 image 分支一致：DB 配置优先（用户配置的 base_url 即网关）
            if provider_conf:
                from app.providers.openai_compatible import OpenAICompatibleVideoProvider

                video_provider: Any = OpenAICompatibleVideoProvider(
                    **_provider_kwargs(provider_conf, include_default_model=False),
                )
            else:
                video_provider = ProviderRegistry.get_video_provider(
                    model,
                    **_provider_kwargs(None, include_default_model=False),
                )
            if video_provider.__class__.__name__ == "MockVideoProvider":
                return None, "视频 Provider 解析为 Mock，未走真实路径"
            result = await video_provider.submit(prompt, model=upstream, **params)
            poll_result = await video_provider.poll(str(result.get("task_id") or ""))
            if poll_result.get("status") != "succeeded":
                err = str(poll_result.get("error") or poll_result.get("status") or "unknown")
                return None, f"真实视频任务未成功: {err[:160]}"
            url = str(poll_result.get("video_url") or "")
            if not url:
                return None, "真实视频结果缺少视频地址"
            data, mime = await _download_media(_rewrite_media_url(url, upstream_base))
            return data, mime, _ext_from_mime(mime, "mp4")
        if task_type in ("audio", "music"):
            speech_provider = ProviderRegistry.get_speech_provider(
                model, **_provider_kwargs(provider_conf)
            )
            if speech_provider.__class__.__name__ == "MockSpeechProvider":
                return None, "语音 Provider 解析为 Mock，未走真实路径"
            result = await speech_provider.submit(prompt, model=upstream, **params)
            poll_result = await speech_provider.poll(str(result.get("task_id") or ""))
            if poll_result.get("status") != "succeeded":
                err = str(poll_result.get("error") or poll_result.get("status") or "unknown")
                return None, f"真实语音任务未成功: {err[:160]}"
            url = str(poll_result.get("audio_url") or "")
            if not url:
                return None, "真实语音结果缺少音频地址"
            data, mime = await _download_media(_rewrite_media_url(url, upstream_base))
            return data, mime, _ext_from_mime(mime, "wav")
        return None, f"任务类型 {task_type} 暂无真实 Provider"
    except Exception as exc:
        reason = str(exc).strip()[:200]
        # httpx ConnectError 等有时消息为空，带上类型名便于定位
        if not reason:
            reason = type(exc).__name__
        logger.warning(
            "real_provider_failed",
            task_type=task_type,
            model=model,
            error=reason,
        )
        return None, reason


async def _generate_cover_image(
    key: str, title: str, style: str, characters: str
) -> bytes | None:
    """封面海报图（文生图）；失败返回 None。"""
    from app.services import comic_service

    chars_line = f"，角色设定：{characters}" if characters.strip() else ""
    prompt = (
        f"电影海报构图，标题《{title}》，{style}风格{chars_line}，"
        "主体角色居中，戏剧化光影，高对比度"
    )
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{comic_service.IMAGE_BASE}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": comic_service.IMAGE_MODEL, "prompt": prompt, "n": 1},
                timeout=180,
            )
            if r.status_code != 200:
                logger.warning("comic_cover_failed", status=r.status_code)
                return None
            return await comic_service._download_result_image(client, r)
    except Exception as exc:
        logger.warning("comic_cover_exc", error=str(exc)[:120])
        return None


async def _comic_real_media(
    prompt: str, params: dict[str, object], db: AsyncSession
) -> dict[str, object] | tuple[None, str]:
    """漫画：分镜（cpa 文本）→ 逐格出图（grok 图片）→ PIL 拼合。

    成功返回 dict：
      {"page": (bytes, mime, ext), "cover": (bytes, mime, ext)|None, "title": str,
       "panels": [{index, data|None, mime, ext, scene, dialogue}]}
    失败返回 (None, reason)。
    """
    from app.services.comic_service import (
        _grok_image_key,
        _story_api_key,
        compose_comic_page,
        compose_cover_page,
        generate_panels,
        generate_storyboard,
        panels_to_json,
    )

    n_panels = max(4, min(9, int(str(params.get("panels") or 4))))
    style = str(params.get("style") or "日式漫画")
    characters = str(params.get("characters") or "")
    layout = "manga" if str(params.get("layout") or "") == "manga" else "grid"
    try:
        story_key = await _story_api_key(db)
        grok_key = await _grok_image_key()
        if not story_key:
            return None, "未配置 cpa 凭据（分镜文本模型不可用）"
        if not grok_key:
            return None, "未配置 grok2api 凭据（出图模型不可用）"
        story = await generate_storyboard(prompt, n_panels, style, characters, story_key)
        panels = story.panels
        title = story.title
        panel_images = await generate_panels(grok_key, panels, style, characters)
        page_data = compose_comic_page(panel_images, panels, n_panels, layout)
        panels_info: list[dict[str, object]] = []
        for i, img in enumerate(panel_images):
            item: dict[str, object] = {
                "index": i,
                "scene": panels[i].scene,
                "dialogue": panels[i].dialogue,
            }
            if img is not None:
                item.update({"data": img, "mime": "image/jpeg", "ext": "jpg"})
            panels_info.append(item)
        # 封面：海报文生图优先，失败用首张成功 panel 兜底
        cover_img = await _generate_cover_image(grok_key, title, style, characters)
        if cover_img is None:
            for img in panel_images:
                if img is not None:
                    cover_img = img
                    break
        cover_page = (
            compose_cover_page(cover_img, title, prompt)
            if cover_img is not None
            else None
        )
        return {
            "page": (page_data, "image/jpeg", "jpg"),
            "cover": (cover_page, "image/jpeg", "jpg") if cover_page is not None else None,
            "title": title,
            "panels": panels_info,
            "storyboard": panels_to_json(panels),
        }
    except Exception as exc:
        reason = str(exc).strip()[:200] or type(exc).__name__
        logger.warning("comic_real_failed", error=reason)
        return None, reason


# 进程内媒体任务串行锁：同 loop 内并发任务排队执行。
# 背景：测试库为内存 SQLite 单连接（StaticPool），并发写会概率性
# 「database is locked/连接竞争」导致全量回归随机失败；串行化后
# 同时只执行一个任务，连接竞争消失。生产走 Celery 队列天然串行，不受影响。
_media_exec_lock: asyncio.Lock | None = None


def _media_lock() -> asyncio.Lock:
    global _media_exec_lock
    if _media_exec_lock is None or _media_exec_lock._loop is not asyncio.get_event_loop():
        _media_exec_lock = asyncio.Lock()
    return _media_exec_lock


async def run_media_task(task_id: str) -> None:
    # 跨进程防双执行：celery worker 与 drain 可能同时拿到同一 queued 任务
    # （锁 TTL 900s > 全局 600s 任务超时，不手动释放）
    from app.core.cache import redis_lock

    if not await redis_lock(f"aigc:lock:media_task:{task_id}", ttl=900):
        return
    async with _media_lock():
        await _run_media_task_locked(task_id)


async def _run_media_task_locked(task_id: str) -> None:
    async with AsyncSessionLocal() as db:
        task = (
            await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
        ).scalar_one_or_none()
        # processing：drain 抢占后交给本执行器（排队中的 queued/submitting 同样执行）
        if task is None or task.status not in ("queued", "submitting", "processing"):
            return

        try:
            params: dict[str, object] = json.loads(task.params or "{}")
            prompt = str(params.get("prompt") or params.get("text") or "")
            # task.model 来自请求；空则按类型取环境默认（无默认则报错，不产占位假数据）。
            model_name = (task.model or "").strip()
            if not model_name:
                if task.task_type == "image":
                    model_name = settings.DEFAULT_IMAGE_PROVIDER or ""
                elif task.task_type in ("audio", "music"):
                    model_name = settings.DEFAULT_SPEECH_PROVIDER or ""
                else:
                    model_name = ""
            # 显式 "mock" 仅保留为测试/开发隔离通道；生产界面不暴露
            use_real = bool(model_name and model_name != "mock")
            if not use_real and model_name != "mock":
                raise RuntimeError(
                    f"未配置可用的{task.task_type} Provider，请在「模型配置」中启用真实模型"
                )

            task.status = "processing"
            await db.commit()

            for pct in _PROGRESS_STEPS:
                await _delay()
                # 期间被取消则终止。
                await db.refresh(task)
                if task.status == "cancelled":
                    logger.info("media_task_cancelled", task_id=task_id)
                    return
                task.progress = pct
                await db.commit()

            # 失败率模拟（默认 0）。
            if settings.MOCK_PROVIDER_FAILURE_RATE > 0 and (
                secrets.randbelow(100) < settings.MOCK_PROVIDER_FAILURE_RATE
            ):
                raise RuntimeError("Mock Provider 模拟失败")

            # ── 尝试真实 Provider ───────────────────────────────
            # 排除 prompt/text/model：model 由上游单独解析，避免 submit(..., model=x, **params) 冲突
            render_params = {
                k: v for k, v in params.items() if k not in ("prompt", "text", "model")
            }
            data: bytes | None = None
            mime = ""
            ext = ""
            used_real = False
            fallback_reason = ""

            if use_real:
                # 漫画：分镜→逐格出图→拼合，返回主资产 + 每格资产
                comic_result: dict[str, object] | tuple[None, str] | None = None
                if task.task_type == "comic":
                    comic_result = await _comic_real_media(prompt, render_params, db)
                    if await _is_cancelled(db, task_id):
                        logger.info("media_task_cancelled", task_id=task_id, stage="after_real")
                        return
                    if isinstance(comic_result, dict) and comic_result.get("page"):
                        page = cast(tuple[bytes, str, str], comic_result["page"])
                        data, mime, ext = page[0], page[1], page[2]
                        used_real = True
                        logger.info("real_provider_succeeded", task_id=task_id, model=model_name)
                    else:
                        fallback_reason = (
                            comic_result[1]
                            if isinstance(comic_result, tuple) and len(comic_result) == 2
                            else "漫画真实生成失败或不可用"
                        )
                else:
                    real_result = await _try_real_media(
                        task.task_type, prompt, render_params, model_name, db
                    )
                    # 真实调用（最长 180s）期间可能被取消：调用后重读，取消则终止
                    if await _is_cancelled(db, task_id):
                        logger.info("media_task_cancelled", task_id=task_id, stage="after_real")
                        return
                    if (
                        isinstance(real_result, tuple)
                        and len(real_result) == 3
                        and real_result[0] is not None
                    ):
                        data, mime, ext = real_result
                        used_real = True
                        logger.info("real_provider_succeeded", task_id=task_id, model=model_name)
                    else:
                        # (None, reason)
                        fallback_reason = (
                            real_result[1]
                            if isinstance(real_result, tuple) and len(real_result) == 2
                            else "真实 Provider 失败或不可用"
                        )

            # ── 真实生成失败：报错落库，不降级占位假数据 ──────────
            if data is None and use_real:
                if not fallback_reason:
                    fallback_reason = "真实 Provider 失败或不可用"
                logger.warning(
                    "real_provider_failed",
                    task_id=task_id,
                    model=model_name,
                    reason=fallback_reason[:200],
                )
                raise RuntimeError(f"真实生成失败：{fallback_reason[:300]}")
            # 显式 "mock"（测试/开发隔离通道）才渲染占位
            if data is None:
                data, mime, ext = media.render_for(task.task_type, prompt, **render_params)

            now = datetime.now(UTC)
            key = f"{task.user_id}/{now:%Y/%m}/{task_id}.{ext}"
            backend = choose_write_backend(task.user_id)
            store = get_storage(backend)
            await store.put(key, data, mime)

            # 漫画：主资产（拼合页）+ 每格资产
            panel_assets: list[dict[str, object]] = []
            comic_panels: list[dict[str, object]] = []
            if task.task_type == "comic" and isinstance(comic_result, dict):
                comic_panels_raw = cast(
                    list[dict[str, object]], comic_result.get("panels") or []
                )
                for p in comic_panels_raw:
                    pdata = p.get("data")
                    pindex = int(str(p.get("index") or 0))
                    comic_panels.append(
                        {
                            "index": pindex,
                            "scene": str(p.get("scene") or ""),
                            "dialogue": str(p.get("dialogue") or ""),
                        }
                    )
                    if pdata is None:
                        continue
                    pdata_bytes = cast(bytes, pdata)
                    pmime, pext = str(p.get("mime") or "image/jpeg"), str(p.get("ext") or "jpg")
                    pkey = f"{task.user_id}/{now:%Y/%m}/{task_id}-panel{pindex}.{pext}"
                    await store.put(pkey, pdata_bytes, pmime)
                    passet = Asset(
                        filename=f"comic-{task_id[:8]}-panel{pindex}.{pext}",
                        storage_key=pkey,
                        storage_backend=backend,
                        mime_type=pmime,
                        size_bytes=len(pdata_bytes),
                        sha256=hashlib.sha256(pdata_bytes).hexdigest(),
                        user_id=task.user_id,
                        task_id=task.id,
                    )
                    db.add(passet)
                    await db.flush()
                    panel_assets.append(
                        {
                            "index": pindex,
                            "asset_id": passet.id,
                            "url": sign_content_url(str(passet.id)),
                            "scene": str(p.get("scene") or ""),
                            "dialogue": str(p.get("dialogue") or ""),
                        }
                    )

            # 漫画：封面页资产
            cover_asset: dict[str, object] | None = None
            if task.task_type == "comic" and isinstance(comic_result, dict):
                cover_raw = comic_result.get("cover")
                if cover_raw is not None:
                    cdata_bytes, cmime, cext = cast(tuple[bytes, str, str], cover_raw)
                    ckey = f"{task.user_id}/{now:%Y/%m}/{task_id}-cover.{cext}"
                    await store.put(ckey, cdata_bytes, cmime)
                    casset = Asset(
                        filename=f"comic-{task_id[:8]}-cover.{cext}",
                        storage_key=ckey,
                        storage_backend=backend,
                        mime_type=cmime,
                        size_bytes=len(cdata_bytes),
                        sha256=hashlib.sha256(cdata_bytes).hexdigest(),
                        user_id=task.user_id,
                        task_id=task.id,
                    )
                    db.add(casset)
                    await db.flush()
                    cover_asset = {
                        "asset_id": casset.id,
                        "url": sign_content_url(str(casset.id)),
                    }

            asset = Asset(
                filename=f"{task.task_type}-{task_id[:8]}.{ext}",
                storage_key=key,
                storage_backend=backend,
                mime_type=mime,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                user_id=task.user_id,
                task_id=task.id,
            )
            db.add(asset)
            try:
                await db.flush()
                # 写终态前重读：取消请求可能刚到达，不允许把已取消任务覆盖为成功
                if await _is_cancelled(db, task_id):
                    logger.info("media_task_cancelled", task_id=task_id, stage="before_terminal")
                    await db.rollback()
                    try:
                        await store.delete(key)
                    except Exception:
                        logger.warning("cancelled_object_cleanup_failed", task_id=task_id)
                    return
                task.status = "succeeded"
                task.progress = 100
                task.result = json.dumps(
                    {
                        "asset_id": asset.id,
                        "url": sign_content_url(str(asset.id)),
                        "access_url_endpoint": f"/api/v1/assets/{asset.id}/access-url",
                        "mime": mime,
                        "is_real": used_real,
                        "provider": model_name if used_real else "mock",
                        "fallback_reason": fallback_reason or None,
                        "reference_photo_id": params.get("reference_photo_id"),
                        "reference_asset_id": params.get("reference_asset_id"),
                        "comic": {
                            "panels": comic_panels,
                            "assets": panel_assets,
                            "storyboard": cast(str, comic_result.get("storyboard") or "")
                            if isinstance(comic_result, dict)
                            else "",
                            "title": cast(str, comic_result.get("title") or "")
                            if isinstance(comic_result, dict)
                            else "",
                            "cover": cover_asset,
                        }
                        if task.task_type == "comic"
                        else None,
                    }
                )
                task.completed_at = now
                await db.commit()
            except Exception:
                # 写库失败：补偿删除对象，避免孤儿
                try:
                    await store.delete(key)
                except Exception:
                    logger.exception(
                        "orphan_object_cleanup_failed",
                        storage_backend=backend,
                        storage_key=key,
                        task_id=task_id,
                    )
                raise
            logger.info(
                "media_task_succeeded",
                task_id=task_id,
                asset_id=asset.id,
                storage_backend=backend,
            )
            await log_call(
                task_id=task_id,
                task_type=task.task_type,
                provider=model_name if used_real else "mock",
                model=model_name,
                status="fallback" if fallback_reason else "succeeded",
                error_message=fallback_reason,
            )
        except Exception as exc:
            await db.rollback()
            task = (
                await db.execute(select(GenerationTask).where(GenerationTask.id == task_id))
            ).scalar_one_or_none()
            if task is not None and task.status != "cancelled":
                task.status = "failed"
                task.error_message = str(exc)[:500]
                task.completed_at = datetime.now(UTC)
                await db.commit()
            logger.exception("media_task_failed", task_id=task_id)
            await log_call(
                task_id=task_id,
                task_type=task.task_type if task else "",
                provider=model_name if "model_name" in locals() else "",
                model=model_name if "model_name" in locals() else "",
                status="failed",
                error_message=str(exc)[:400],
            )
