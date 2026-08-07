import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.provider_config import ProviderConfig
from app.models.user import User
from app.schemas.provider import (
    ProviderConfigCreate,
    ProviderConfigResponse,
    ProviderConfigUpdate,
    ProviderPublicItem,
)
from app.security.auth import get_current_user, require_role
from app.security.ownership import seal_secret, secret_fingerprint
from app.services.provider_resolver import list_enabled_text_catalog

router = APIRouter()


def _to_admin_response(p: ProviderConfig) -> ProviderConfigResponse:
    return ProviderConfigResponse(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        base_url=p.base_url,
        default_model=p.default_model,
        is_enabled=p.is_enabled,
        priority=p.priority,
        timeout_seconds=getattr(p, "timeout_seconds", 60) or 60,
        created_at=p.created_at,
        has_api_key=bool(p.encrypted_api_key),
        api_key_fingerprint=secret_fingerprint(p.encrypted_api_key or ""),
    )


@router.get("/catalog", response_model=list[ProviderPublicItem])
async def provider_catalog(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ProviderPublicItem]:
    """文本生成等用的模型目录（含 mock / DB / env）。

    openai_compatible 条目附带轻量健康探测（2s 超时并发）：
    前端据此标记「维护中」，避免用户选到不可用模型。
    """
    raw = await list_enabled_text_catalog(db)
    items = [ProviderPublicItem(**item) for item in raw]
    await _attach_health(items)
    return items


async def _attach_health(items: list[ProviderPublicItem]) -> None:
    """并发探测 openai_compatible 条目的 base_url 可达性（探测 /health 与 /）。"""
    import httpx

    async def probe(item: ProviderPublicItem) -> bool:
        if item.provider_type in ("mock", "builtin") or item.id == "mock":
            return True
        # 从 catalog 拿不到 base_url：按 id 反查 ProviderConfig
        from app.core.database import AsyncSessionLocal
        from app.models.provider_config import ProviderConfig

        async with AsyncSessionLocal() as db:
            cfg = (
                await db.execute(
                    select(ProviderConfig).where(ProviderConfig.id == item.id)
                )
            ).scalar_one_or_none()
            base = (cfg.base_url if cfg else "") or ""
        if not base:
            return True
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                for path in ("/health", "/"):
                    try:
                        r = await client.get(base.rstrip("/") + path)
                        if r.status_code < 500:
                            return True
                    except Exception:
                        continue
            return False
        except Exception:
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


@router.get("/admin", response_model=list[ProviderConfigResponse])
async def list_providers_admin(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> list[ProviderConfigResponse]:
    result = await db.execute(select(ProviderConfig).order_by(ProviderConfig.priority))
    return [_to_admin_response(p) for p in result.scalars().all()]


@router.post("/", response_model=ProviderConfigResponse)
async def create_provider(
    req: ProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> ProviderConfigResponse:
    provider = ProviderConfig(
        name=req.name.strip(),
        provider_type=(req.provider_type or "text").strip() or "text",
        base_url=(req.base_url or "").strip(),
        default_model=(req.default_model or "").strip(),
        is_enabled=req.is_enabled,
        priority=req.priority,
        timeout_seconds=req.timeout_seconds,
        encrypted_api_key=seal_secret(req.api_key) if req.api_key else "",
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return _to_admin_response(provider)


@router.post("/import-env", response_model=ProviderConfigResponse)
async def import_from_env(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> ProviderConfigResponse:
    """把当前 .env 的 OPENAI_COMPATIBLE_* 导入为一条可编辑配置。"""
    base = (settings.OPENAI_COMPATIBLE_BASE_URL or "").strip()
    if not base:
        raise HTTPException(status_code=400, detail="环境变量未配置 OPENAI_COMPATIBLE_BASE_URL")
    model = (settings.OPENAI_COMPATIBLE_MODEL or "default").strip()
    # 已存在同 base+model 则更新 key
    existing = (
        await db.execute(
            select(ProviderConfig).where(
                ProviderConfig.base_url == base,
                ProviderConfig.default_model == model,
            )
        )
    ).scalar_one_or_none()
    key = settings.OPENAI_COMPATIBLE_API_KEY or "none"
    if existing:
        existing.encrypted_api_key = seal_secret(key)
        existing.is_enabled = True
        existing.name = existing.name or f"Env · {model}"
        await db.commit()
        await db.refresh(existing)
        return _to_admin_response(existing)

    provider = ProviderConfig(
        name=f"Env · {model}",
        provider_type="openai_compatible",
        base_url=base,
        default_model=model,
        is_enabled=True,
        priority=10,
        encrypted_api_key=seal_secret(key),
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return _to_admin_response(provider)


@router.put("/{provider_id}", response_model=ProviderConfigResponse)
async def update_provider(
    provider_id: str,
    req: ProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> ProviderConfigResponse:
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    data = req.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(provider, field, value)
    if api_key:  # 非空才轮换密钥
        provider.encrypted_api_key = seal_secret(api_key)
    await db.commit()
    await db.refresh(provider)
    return _to_admin_response(provider)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_role("admin"))
) -> dict[str, object]:
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    # 若仍被 generation_tasks 引用，改为停用，避免外键 500
    from sqlalchemy import func

    from app.models.generation_task import GenerationTask

    ref_count = (
        await db.execute(
            select(func.count(GenerationTask.id)).where(GenerationTask.provider_id == provider_id)
        )
    ).scalar() or 0
    if ref_count > 0:
        provider.is_enabled = False
        if not provider.name.endswith("（停用）"):
            provider.name = f"{provider.name}（停用）"
        await db.commit()
        return {
            "success": True,
            "data": {
                "soft_deleted": True,
                "reason": f"仍有 {ref_count} 条任务引用，已停用而非物理删除",
                "id": provider_id,
            },
        }
    await db.delete(provider)
    await db.commit()
    return {"success": True, "data": None}
