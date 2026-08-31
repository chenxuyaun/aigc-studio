"""Applications - Comic 委派桥（P4-2 从 core.runtime.comic_bridge 冻结点归位）。

现状：saiOS Comic 业务（分镜→出图→拼合）**完全**在 services/comic_service.py。
但 task_runner.py **直接**调 comic_service 函数（Core → Domain 反向依赖，P0 标注 P4 处理）。

P0 临时方案：把 Comic 任务处理**整个抽到**本模块的 `run_comic_task(task_id, params, db)`，
让 task_runner.py 通过本桥接调用 Comic 业务，**不再直接 import services/comic_service**。

P4 时这个桥接 + 整个 Comic 业务**整体**移到 `app/applications/comic/` 下。
"""
# ruff: noqa: E402  # P0 约定：comic_service 的桥接 import 必须居中（仅本模块 import）
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, cast

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.media_access import sign_content_url
from app.core.config import settings  # noqa: F401
from app.models.asset import Asset
from app.storage import choose_write_backend, get_storage

logger = structlog.get_logger()


# ── P0 桥接：从 comic_service 导入，但**仅在本模块**有 import ──
# task_runner.py 通过本模块的 run_comic_task() 间接调 Comic 业务。
from app.applications import (
    comic_service as _comic_svc,  # P0 约定：仅本模块 import comic_service
)
from app.applications.comic_service import (
    compose_comic_page,
    compose_cover_page,
    generate_panels,
    generate_storyboard,
    panels_to_json,
)


async def _generate_cover_image(
    key: str, title: str, style: str, characters: str
) -> bytes | None:
    """封面海报图（文生图）；失败返回 None。"""
    chars_line = f"，角色设定：{characters}" if characters.strip() else ""
    prompt = (
        f"电影海报构图，标题《{title}》，{style}风格{chars_line}，"
        "主体角色居中，戏剧化光影，高对比度"
    )
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{_comic_svc.IMAGE_BASE}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": _comic_svc.IMAGE_MODEL, "prompt": prompt, "n": 1},
                timeout=180,
            )
            if r.status_code != 200:
                logger.warning("comic_cover_failed", status=r.status_code)
                return None
            return await _comic_svc._download_result_image(client, r)
    except Exception as exc:
        logger.warning("comic_cover_exc", error=str(exc)[:120])
        return None


async def _comic_real_media(
    prompt: str, params: dict[str, object], db: AsyncSession
) -> dict[str, object] | tuple[None, str]:
    """漫画：分镜（cpa 文本）→ 逐格出图（grok 图片）→ PIL 拼合。

    @todo P4 (Applications 阶段) — 整段 Comic 业务（含本函数 + _generate_cover_image）应
    迁移到 `app/applications/comic/` 下，由 Comic Application 通过 Runtime Tool / MCP 暴露面
    调用，Core (task_runner) 不应直接 import Domain。本模块临时作为 P0 桥接。
    """
    n_panels = max(4, min(9, int(str(params.get("panels") or 4))))
    style = str(params.get("style") or "日式漫画")
    characters = str(params.get("characters") or "")
    layout = "manga" if str(params.get("layout") or "") == "manga" else "grid"
    try:
        story_key = await _comic_svc._story_api_key(db)
        grok_key = await _comic_svc._grok_image_key()
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
        cover_img = await _generate_cover_image(grok_key, title, style, characters)
        if cover_img is None:
            for img in panel_images:
                if img is not None:
                    cover_img = img
                    break
        cover_page = (
            compose_cover_page(cover_img, title, prompt) if cover_img is not None else None
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


async def _write_comic_subassets(
    db: AsyncSession, task: Any, comic_result: dict, now: datetime
) -> tuple[list, dict | None]:
    """Comic panels/cover 子资产落库（保持 P0 之前的落库行为不变）。"""
    panel_assets: list[dict[str, object]] = []
    comic_panels: list[dict[str, object]] = []

    backend = choose_write_backend(task.user_id)
    store = get_storage(backend)

    panels_raw = cast(list[dict[str, object]], comic_result.get("panels") or [])
    for p in panels_raw:
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
        pmime, pext = (
            str(p.get("mime") or "image/jpeg"),
            str(p.get("ext") or "jpg"),
        )
        pkey = f"{task.user_id}/{now:%Y/%m}/{task.id}-panel{pindex}.{pext}"
        await store.put(pkey, pdata_bytes, pmime)
        passet = Asset(
            filename=f"comic-{task.id[:8]}-panel{pindex}.{pext}",
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

    cover_asset: dict[str, object] | None = None
    cover_raw = comic_result.get("cover")
    if cover_raw is not None:
        cdata_bytes, cmime, cext = cast(tuple[bytes, str, str], cover_raw)
        ckey = f"{task.user_id}/{now:%Y/%m}/{task.id}-cover.{cext}"
        await store.put(ckey, cdata_bytes, cmime)
        casset = Asset(
            filename=f"comic-{task.id[:8]}-cover.{cext}",
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
    return panel_assets, cover_asset
