"""Core Runtime - 候选链 + Provider 构建。

从 services/task_runner.py 拆出：
- _provider_kwargs: provider 构造参数
- _media_candidates: 智能路由 + 候选链 + last_ok 过滤
- _build_image_provider: 按 provider_type 构建 Image provider
- _load_reference_image: 参考图（写真 Photo 或素材 Asset）→ data URL

P0 边界：task_runner.py 通过 `from app.core.runtime.candidate import ...` 使用。
P0 不动 _try_real_media（仍在 task_runner.py，作为门面，调用 _media_candidates + _build_image_provider）。
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.model_hub_client import get_active_chain  # noqa: F401
from app.storage import get_storage

logger = logging.getLogger(__name__)


# ── 槽位 → 候选链 ──
_SLOT_BY_TASK: dict[str, str] = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "music": "music",
    "text": "text",
    "comic": "image",  # comic 复用 image 链
}


def _provider_kwargs(
    settings_row: tuple[str, str, str, str] | None,
    *,
    include_default_model: bool = True,
) -> dict[str, Any]:
    """组装 provider 构造参数。图片/视频分支不传 default_model：
    DB 的 default_model 是文本模型（grok-chat-fast），上游图片/视频端点
    需要各自的内置默认（grok-imagine-image / grok-imagine-video）。
    """
    if settings_row is None:
        return {}
    base_url, api_key, default_model, _provider_type = settings_row
    kwargs = {
        "base_url": base_url,
        "api_key": api_key or "none",
    }
    if include_default_model:
        kwargs["default_model"] = default_model
    return kwargs


async def _media_candidates(
    db: AsyncSession, model: str, task_type: str
) -> list[tuple[str, str, str, str] | None]:
    """v3 故障转移候选链：模型中心对应槽位的候选列表（主选在前）。

    P2（deprecation-plan.md）：saiOS DB 单候选回退已下线——
    链为空/模型中心不可用时返回 [None]（registry 兜底）。
    元素 None 表示走 ProviderRegistry 解析（与旧行为一致）。
    """
    _ = db  # P2 起不再查 DB；参数保留兼容调用方
    try:
        slot = _SLOT_BY_TASK.get((task_type or "").lower())
        if slot:
            chain = await get_active_chain(slot)
            if not chain:
                # batch15: hub 拉取瞬态失败有 10s 负缓存——媒体槽位有配置时空链
                # 几乎必为瞬态（music succeeded 与 video failed 仅差 4 分钟实证）。
                # 等过负缓存窗口重试一次，仍空才认输。
                logger.warning("media_chain_empty_retry, slot=%s", slot)
                await asyncio.sleep(1.5)
                chain = await get_active_chain(slot)
        # 智能路由：本地 GPU 离线时（last_ok != 1）跳过，不傻等 submit 超时
        raw = [
            (
                c.get("base_url", ""),
                c.get("api_key", ""),
                c.get("default_model", ""),
                (c.get("provider_type") or "").lower().strip(),
                int(c.get("last_ok") or 0),
            )
            for c in chain
            if c.get("base_url") or (c.get("provider_type") or "").lower() == "edge_tts"
        ]
        confs: list[tuple[str, str, str, str]] = []
        for base_url, api_key, model, pt, last_ok in raw:
            is_local_gpu = "172.17.0.1:700" in (base_url or "")
            if is_local_gpu and last_ok != 1:
                # batch15: stdlib logging 不收任意 kwargs——原 kwargs 写法在这里
                # 必抛 TypeError（Logger._log unexpected keyword），被外层 except
                # 吞掉后整条候选链崩成 [None]→Mock 拒绝。改为位置参数格式。
                logger.info(
                    "media_skip_offline_gpu slot=%s base_url=%s last_ok=%s",
                    pt, base_url, last_ok,
                )
                continue
            confs.append((base_url, api_key, model, pt))
        if not confs and raw:
            # 全离线时保留原链（兜底试一次，万一探活过期了）
            confs = [(b, a, m, p) for b, a, m, p, _ in raw]
        if confs:
            return confs
        if slot:
            logger.warning("media_candidates_empty_chain, slot=%s", slot)
    except Exception as exc:  # noqa: BLE001
        logger.warning("media_candidates_error, slot=%s, err=%s", slot, str(exc)[:120])
    return [None]


def _build_image_provider(conf: tuple[str, str, str, str] | None) -> Any | None:
    """按 provider_type 构建图像 provider；conf=None 返回 None（registry 路径）。"""
    if conf is None:
        return None
    if conf[3] == "zarklab":
        from app.providers.models.zarklab import ZarklabImageProvider

        return ZarklabImageProvider(
            **_provider_kwargs(conf, include_default_model=False)
        )
    if conf[3] == "chat_image":
        from app.providers.models.chat_image import ChatCompletionsImageProvider

        return ChatCompletionsImageProvider(**_provider_kwargs(conf))
    if conf[3] == "comfyui_image":
        from app.providers.models.comfyui import ComfyUIImageProvider

        return ComfyUIImageProvider(**_provider_kwargs(conf))
    from app.providers.models.openai_compatible import OpenAICompatibleImageProvider

    return OpenAICompatibleImageProvider(
        **_provider_kwargs(conf, include_default_model=False)
    )


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
