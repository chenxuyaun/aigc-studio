"""Core Runtime - 真实 Provider 执行器（候选链 + submit/poll + 降级）。

从 services/task_runner.py 拆出 `_try_real_media`。

P0 边界：task_runner.py 通过 `from app.core.runtime.executor import ...` 使用。

Comic 业务**不**在此（保留在 task_runner.py，P4 移 applications/comic/）。
"""
from __future__ import annotations

import logging
from typing import Any, cast

import structlog

from app.core.runtime.candidate import (
    _build_image_provider,
    _load_reference_image,
    _media_candidates,
    _provider_kwargs,
)
from app.core.runtime.asset_writer import (
    _download_media,
    _ext_from_mime,
    _rewrite_media_url,
)
from app.providers.registry import ProviderRegistry
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def _upstream_model_id(model: str) -> str:
    """别名 → 空串（用 Provider 默认模型）；具体 id（如 org/model）原样保留。"""
    raw = (model or "").strip()
    if not raw or raw.lower() in _PROVIDER_ALIASES:
        return ""
    return raw


# 已识别的 Provider 别名（Hub 默认模型名，落到 Provider 自带的默认）
_PROVIDER_ALIASES: frozenset[str] = frozenset(
    {"default", "auto", "mock", "huggingface", "default-image", "default-video"}
)


async def _try_real_media(
    task_type: str,
    prompt: str,
    params: dict[str, object],
    model: str,
    db: AsyncSession,
) -> tuple[bytes, str, str] | tuple[None, str]:
    """尝试真实 Provider。

    成功: (bytes, mime, ext)
    失败: (None, reason) — reason 供 result.fallback_reason 展示。

    Comic 类型**不**走此函数（保留在 task_runner.py 的 _comic_real_media，P4 移 applications/comic/）。
    """
    upstream = _upstream_model_id(model)
    candidates = await _media_candidates(db, model, task_type)
    try:
        if task_type == "image":
            submit_params = dict(params)
            if params.get("reference_photo_id") or params.get("reference_asset_id"):
                ref_url, ref_err = await _load_reference_image(db, params)
                if ref_url:
                    submit_params["image"] = ref_url
                elif ref_err:
                    logger.warning("reference_skip, task_id=%s, reason=%s", model, ref_err)
            last_reason = ""
            for i, conf in enumerate(candidates):
                try:
                    if conf is None:
                        image_provider: Any = ProviderRegistry.get_image_provider(
                            model,
                            **_provider_kwargs(None, include_default_model=False),
                        )
                        # 降级到 registry 路径时用上游模型
                        current_model = upstream
                    else:
                        image_provider = _build_image_provider(conf)
                        # 批17: 降级 bug 修复——用当前候选的 default_model（conf[2]），
                        # 而不是固定的 upstream（FLUX 名字）。否则候选 4/4 grok2api 收到
                        # "model=flux1-schnell" 会 400 "not an image model"。
                        current_model = conf[2] or upstream
                    if image_provider is None or image_provider.__class__.__name__ == "MockImageProvider":
                        return None, "图像 Provider 解析为 Mock，未走真实路径"
                    result = await image_provider.submit(
                        prompt, model=current_model, **submit_params
                    )
                    poll_result = await image_provider.poll(str(result.get("task_id") or ""))
                    if poll_result.get("status") != "succeeded":
                        raise RuntimeError(
                            str(poll_result.get("error") or poll_result.get("status") or "unknown")
                        )
                    url = str(poll_result.get("image_url") or "")
                    if not url:
                        raise RuntimeError("真实图像结果缺少图片地址")
                    data, mime = await _download_media(
                        _rewrite_media_url(url, conf[0] if conf else "")
                    )
                    logger.info(
                        "media_candidate_used",
                        task_type=task_type,
                        candidate=f"{i + 1}/{len(candidates)}",
                        provider_type=(conf[3] if conf else "registry"),
                    )
                    return data, mime, _ext_from_mime(mime, "bin")
                except Exception as exc:  # noqa: BLE001 — 单候选失败降级到下一个
                    last_reason = (str(exc).strip() or type(exc).__name__)[:200]
                    if i < len(candidates) - 1:
                        logger.warning(
                            "media_failover_next",
                            task_type=task_type,
                            failed_candidate=i + 1,
                            error=last_reason,
                            remaining=len(candidates) - i - 1,
                        )
                        continue
            return None, f"真实图像任务未成功: {last_reason[:160]}"
        if task_type == "video":
            last_reason = ""
            for i, conf in enumerate(candidates):
                try:
                    if conf is None:
                        video_provider: Any = ProviderRegistry.get_video_provider(
                            model,
                            **_provider_kwargs(None, include_default_model=False),
                        )
                    elif (conf[3] or "").lower() == "comfyui":
                        from app.providers.comfyui import ComfyUIProvider

                        video_provider = ComfyUIProvider(**_provider_kwargs(conf))
                    elif (conf[3] or "").lower() == "minimax_video":
                        # 批14：MiniMax Hailuo（H3）云 API——GPU 节点离线时的第二候选
                        from app.providers.minimax_video import MinimaxVideoProvider

                        video_provider = MinimaxVideoProvider(**_provider_kwargs(conf))
                    else:
                        from app.providers.openai_compatible import (
                            OpenAICompatibleVideoProvider,
                        )

                        video_provider = OpenAICompatibleVideoProvider(
                            **_provider_kwargs(conf, include_default_model=False),
                        )
                    if video_provider.__class__.__name__ == "MockVideoProvider":
                        return None, "视频 Provider 解析为 Mock，未走真实路径"
                    result = await video_provider.submit(
                        prompt, model=conf[2] or upstream, **params
                    )
                    poll_result = await video_provider.poll(str(result.get("task_id") or ""))
                    if poll_result.get("status") != "succeeded":
                        raise RuntimeError(
                            str(poll_result.get("error") or poll_result.get("status") or "unknown")
                        )
                    url = str(poll_result.get("video_url") or "")
                    if not url:
                        raise RuntimeError("真实视频结果缺少视频地址")
                    data, mime = await _download_media(
                        _rewrite_media_url(url, conf[0] if conf else "")
                    )
                    logger.info(
                        "media_candidate_used",
                        task_type=task_type,
                        candidate=f"{i + 1}/{len(candidates)}",
                        provider_type=(conf[3] if conf else "registry"),
                    )
                    return data, mime, _ext_from_mime(mime, "mp4")
                except Exception as exc:  # noqa: BLE001
                    last_reason = (str(exc).strip() or type(exc).__name__)[:200]
                    if i < len(candidates) - 1:
                        logger.warning(
                            "media_failover_next",
                            task_type=task_type,
                            failed_candidate=i + 1,
                            error=last_reason,
                            remaining=len(candidates) - i - 1,
                        )
                        continue
            return None, f"真实视频任务未成功: {last_reason[:160]}"
        if task_type in ("audio", "music"):
            last_reason = ""
            for i, conf in enumerate(candidates):
                try:
                    ptype = (conf[3] if conf else "").lower()
                    if conf and ptype == "edge_tts":
                        from app.providers.edge_tts import EdgeTTSSpeechProvider

                        speech_provider = EdgeTTSSpeechProvider()
                        # hub 的 default_model 存音色（如 zh-CN-XiaoxiaoNeural）；
                        # 请求 schema 默认 voice="default" 视为未指定
                        if conf[2] and str(params.get("voice") or "") in ("", "default"):
                            params = {**params, "voice": str(conf[2])}
                    elif conf and ptype == "musicgen":
                        from app.providers.musicgen import MusicGenProvider

                        # 16GB GPU 节点经 frp 隧道提供 MusicGen（音乐长文本用 duration 参数）
                        speech_provider = MusicGenProvider(**_provider_kwargs(conf))
                    else:
                        # registry 兜底：get_speech_provider 只收 name，
                        # 不能传 base_url 等构造参数（历史 TypeError 隐患）
                        speech_provider = ProviderRegistry.get_speech_provider(
                            upstream or ""
                        )
                    if speech_provider.__class__.__name__ == "MockSpeechProvider":
                        return None, "语音 Provider 解析为 Mock，未走真实路径"
                    result = await speech_provider.submit(
                        prompt, model=conf[2] or upstream, **params
                    )
                    poll_result = await speech_provider.poll(str(result.get("task_id") or ""))
                    if poll_result.get("status") != "succeeded":
                        raise RuntimeError(
                            str(poll_result.get("error") or poll_result.get("status") or "unknown")
                        )
                    url = str(
                        poll_result.get("audio_url") or result.get("audio_url") or ""
                    )
                    if not url:
                        raise RuntimeError("真实语音结果缺少音频地址")
                    data, mime = await _download_media(
                        _rewrite_media_url(url, conf[0] if conf else "")
                    )
                    logger.info(
                        "media_candidate_used",
                        task_type=task_type,
                        candidate=f"{i + 1}/{len(candidates)}",
                        provider_type=(conf[3] if conf else "registry"),
                    )
                    return data, mime, _ext_from_mime(mime, "wav")
                except Exception as exc:  # noqa: BLE001
                    last_reason = (str(exc).strip() or type(exc).__name__)[:200]
                    if i < len(candidates) - 1:
                        logger.warning(
                            "media_failover_next",
                            task_type=task_type,
                            failed_candidate=i + 1,
                            error=last_reason,
                            remaining=len(candidates) - i - 1,
                        )
                        continue
            return None, f"真实语音任务未成功: {last_reason[:160]}"
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
