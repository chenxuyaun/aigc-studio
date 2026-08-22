"""Provider 目录路由（P3 收敛版）。

deprecation-plan.md：saiOS DB `provider_configs` 表已删除，供应商管理唯一入口 =
模型中心（服务器 :8511）。本路由仅保留：
- GET /catalog 与 GET / ：登录用户可见的脱敏模型目录（来源=模型中心，env 兜底条目）
- 写操作 410 Gone 桩（外部兼容）
admin 列表与 /test 探测已随表删除。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.provider import ProviderPublicItem
from app.security.auth import get_current_user, require_role
from app.services.provider_resolver import list_enabled_text_catalog

router = APIRouter()


def _gone() -> HTTPException:
    """P2/P3：供应商写操作已下线，统一 410 指引模型中心。"""
    return HTTPException(
        status_code=410,
        detail="供应商写操作已下线：请使用模型中心（服务器 :8511）管理供应商",
    )


@router.get("/catalog", response_model=list[ProviderPublicItem])
async def provider_catalog(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProviderPublicItem]:
    """文本生成等用的模型目录（hub 条目 + env 兜底；无 mock 假数据路径）。"""
    raw = await list_enabled_text_catalog(db)
    items = [ProviderPublicItem(**item) for item in raw]
    await _attach_health(items)
    return items


async def _attach_health(items: list[ProviderPublicItem]) -> None:
    """轻量可达性探测：env 条目探 settings 配置的 base_url；hub 条目视为健康
    （其健康状态在模型中心 UI 有专门展示，此处不重复探测内网上游）。"""
    import httpx

    async def probe(item: ProviderPublicItem) -> bool:
        if item.source != "env":
            return True
        base = (settings.OPENAI_COMPATIBLE_BASE_URL or "").strip()
        if not base:
            return True
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                for path in ("/health", "/"):
                    try:
                        r = await client.get(base.rstrip("/") + path)
                        if r.status_code < 500:
                            return True
                    except Exception:  # noqa: BLE001
                        continue
            return False
        except Exception:  # noqa: BLE001
            return False

    results = await asyncio.gather(*(probe(it) for it in items))
    for item, ok in zip(items, results, strict=True):
        item.healthy = ok


@router.get("/", response_model=list[ProviderPublicItem])
async def list_providers_public(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ProviderPublicItem]:
    # 与 catalog 对齐，兼容旧路径
    return await provider_catalog(db, user)


# ── 已下线的写/管理端点（410 桩，保持外部调用方可诊断）──────────────────


@router.post("/")
async def create_provider(_: User = Depends(require_role("admin"))) -> dict[str, object]:
    raise _gone()


@router.post("/import-env")
async def import_from_env(_: User = Depends(require_role("admin"))) -> dict[str, object]:
    raise _gone()


@router.get("/admin")
async def list_providers_admin(_: User = Depends(require_role("admin"))) -> dict[str, object]:
    raise _gone()


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str, _: User = Depends(require_role("admin"))
) -> dict[str, object]:
    _ = provider_id
    raise _gone()


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str, _: User = Depends(require_role("admin"))
) -> dict[str, object]:
    _ = provider_id
    raise _gone()


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str, _: User = Depends(require_role("admin"))
) -> dict[str, object]:
    _ = provider_id
    raise _gone()
