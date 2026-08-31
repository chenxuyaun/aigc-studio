"""Core Runtime - Model Hub Router 客户端（v3 故障转移链）。

从 services/model_hub_client.py 抽离：
- get_active_chain: v3 候选链（按降级顺序）
- get_active_config: 槽位主选 provider
- list_providers: Hub 全部 provider
- _fetch_active: /api/active 全量响应（短缓存 + 故障降级）
- _base_url / _extract_slot: 辅助工具
"""
from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()

_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_LOG_THROTTLE: dict[str, float] = {"fail_ts": 0.0}


def _base_url() -> str:
    return (settings.MODEL_HUB_BASE_URL or "http://127.0.0.1:8511").rstrip("/")


def _extract_slot(data: dict[str, Any], slot: str | None) -> dict[str, Any] | None:
    """从 /api/active 响应提取指定槽位配置；slot 为空走兼容 config（= text）。"""
    if slot:
        pub = (data.get("slots") or {}).get(slot)
        if not pub or not isinstance(pub, dict):
            return None
        return {
            "base_url": str(pub.get("base_url") or ""),
            "api_key": str(pub.get("api_key") or ""),
            "default_model": str(pub.get("default_model") or ""),
            "provider_type": str(pub.get("provider_type") or "").lower().strip(),
        }
    cfg = data.get("config")
    if not cfg or not isinstance(cfg, dict):
        return None
    return {
        "base_url": str(cfg.get("base_url") or ""),
        "api_key": str(cfg.get("api_key") or ""),
        "default_model": str(cfg.get("default_model") or ""),
        "provider_type": str(cfg.get("provider_type") or "").lower().strip(),
    }


async def get_active_chain(slot: str) -> list[dict[str, Any]]:
    """v3 故障转移链：返回槽位的候选列表（按降级顺序，主选在前）。

    复用 /api/active 响应（与 get_active_config 同缓存）；模型中心不可用/链为空
    时返回 []，调用方回退 saiOS 自带配置。元素结构与 _provider_settings 对齐：
      {base_url, api_key, default_model, provider_type}
    """
    data = await _fetch_active()
    if not data:
        return []
    chain = (data.get("slots_chain") or {}).get(slot) or []
    out: list[dict[str, Any]] = []
    for pub in chain:
        # edge_tts 类本地型 provider 无 base_url（免密钥），不能被过滤掉
        if isinstance(pub, dict) and (
            pub.get("base_url")
            or str(pub.get("provider_type") or "").lower().strip() == "edge_tts"
        ):
            out.append({
                "base_url": str(pub.get("base_url") or ""),
                "api_key": str(pub.get("api_key") or ""),
                "default_model": str(pub.get("default_model") or ""),
                "provider_type": str(pub.get("provider_type") or "").lower().strip(),
                "last_ok": int(pub.get("last_ok") or 0),
            })
    return out


async def _fetch_active() -> dict[str, Any] | None:
    """拉取 /api/active 全量响应（带共享短缓存；失败返回 None）。"""
    cache_seconds = float(getattr(settings, "MODEL_HUB_CACHE_SECONDS", 10) or 10)
    now = time.monotonic()
    cached = _cache.get("__payload__")
    if isinstance(cached, dict) and now - _cache["ts"] < cache_seconds:
        return cached.get("data")
    try:
        timeout = float(getattr(settings, "MODEL_HUB_TIMEOUT", 2) or 2)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_base_url()}/api/active")
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
        _cache["__payload__"] = {"data": data}
        _cache["ts"] = now
        return data
    except Exception as exc:
        _cache["__payload__"] = {"data": None}
        _cache["ts"] = now
        if now - _LOG_THROTTLE["fail_ts"] > 60:
            _LOG_THROTTLE["fail_ts"] = now
            logger.warning(
                "model_hub_unreachable",
                base=_base_url(),
                error=f"{type(exc).__name__}: {exc}"[:120],
            )
        return None


async def get_active_config(slot: str | None = None) -> dict[str, Any] | None:
    """返回模型中心指定槽位（默认 text）的主选 provider 配置；不可用/未激活返回 None。

    返回结构（与 _provider_settings 对齐）：
      {base_url, api_key, default_model, provider_type}
    """
    data = await _fetch_active()
    if data is None:
        return None
    cfg = _extract_slot(data, slot)
    if cfg:
        logger.debug(
            "model_hub_active_hit",
            slot=slot or "legacy",
            provider_type=cfg.get("provider_type"),
            model=cfg.get("default_model"),
        )
    else:
        logger.debug("model_hub_slot_empty", slot=slot or "legacy")
    return cfg


async def list_providers() -> list[dict[str, Any]]:
    """拉取模型中心全部供应商（P2：saiOS 前端目录改由模型中心供给）。

    失败返回 []（调用方回退 env 条目），带独立短缓存。
    """
    cache_seconds = float(getattr(settings, "MODEL_HUB_CACHE_SECONDS", 10) or 10)
    now = time.monotonic()
    cached = _cache.get("__providers__")
    if isinstance(cached, list) and now - _cache.get("providers_ts", 0.0) < cache_seconds:
        return cached
    try:
        timeout = float(getattr(settings, "MODEL_HUB_TIMEOUT", 2) or 2)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_base_url()}/api/providers")
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
        out = [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []
        _cache["__providers__"] = out
        _cache["providers_ts"] = now
        return out
    except Exception as exc:
        _cache["__providers__"] = []
        _cache["providers_ts"] = now
        if now - _LOG_THROTTLE["fail_ts"] > 60:
            _LOG_THROTTLE["fail_ts"] = now
            logger.warning(
                "model_hub_providers_unreachable",
                base=_base_url(),
                error=f"{type(exc).__name__}: {exc}"[:120],
            )
        return []
