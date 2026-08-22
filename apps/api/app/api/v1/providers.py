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
from app.security.ownership import open_secret, seal_secret, secret_fingerprint
from app.services.provider_resolver import list_enabled_text_catalog

router = APIRouter()


def _gone() -> HTTPException:
    """P2：供应商写操作已下线，统一 410 指引模型中心。"""
    return HTTPException(
        status_code=410,
        detail="供应商写操作已下线：请使用模型中心（服务器 :8511）管理供应商",
    )


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
                await db.execute(select(ProviderConfig).where(ProviderConfig.id == item.id))
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
    raise _gone()


@router.post("/import-env", response_model=ProviderConfigResponse)
async def import_from_env(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> ProviderConfigResponse:
    """P2：已下线（原：把 .env 的 OPENAI_COMPATIBLE_* 导入为一条可编辑配置）。"""
    raise _gone()


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> dict[str, object]:
    """从服务器真实探测一个 Provider 的连通性，并返回上游可用的模型列表。

    公益 OpenAI 兼容地址最需要这一步：base_url + key 能不能用、有哪些模型，点一下见分晓。
    - 优先 GET {base_url}/models（带 key）列模型；
    - /models 不可用或失败时，回退最小 chat.completions 探测（只回显 echo，不发完整生成）。
    """
    result = await db.execute(select(ProviderConfig).where(ProviderConfig.id == provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider 不存在")
    base = (provider.base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "message": "base_url 为空，无法测试"}

    key = open_secret(provider.encrypted_api_key or "") or ""
    headers = {"Authorization": f"Bearer {key}"} if key and key != "none" else {}
    import httpx

    started = asyncio.get_event_loop().time()
    timeout = max(int(provider.timeout_seconds or 60), 15)

    # 1) /models 列模型
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(base + "/models", headers=headers)
        latency_ms = int((asyncio.get_event_loop().time() - started) * 1000)
        if r.status_code < 500:
            data = r.json() if r.content else {}
            models: list[str] = []
            for item in data.get("data") if isinstance(data, dict) else []:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    models.append(item["id"])
            if models:
                return {
                    "ok": True,
                    "method": "models",
                    "latency_ms": latency_ms,
                    "models": models,
                    "message": f"连通正常，上游共 {len(models)} 个模型",
                }
            # /models 返回 OK 但无 data（部分公益站如此），视为账号/网关可用
            return {
                "ok": True,
                "method": "models",
                "latency_ms": latency_ms,
                "models": [],
                "message": f"网关可达（HTTP {r.status_code}），未返回模型列表",
            }
        upstream_err = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:  # noqa: BLE001 - 网络探测失败统一归为不可达
        upstream_err = f"网络不可达: {type(e).__name__} {e}"

    # 2) 回退最小 chat 探测
    fallback_model = (provider.default_model or "").strip() or "gpt-3.5-turbo"
    payload = {
        "model": fallback_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                base + "/chat/completions", json=payload, headers={"Content-Type": "application/json", **headers}
            )
        latency_ms = int((asyncio.get_event_loop().time() - started) * 1000)
        if r.status_code < 500:
            return {
                "ok": True,
                "method": "chat",
                "latency_ms": latency_ms,
                "models": [fallback_model],
                "message": f"聊天探测通过（HTTP {r.status_code}），模型 {fallback_model}",
            }
        return {
            "ok": False,
            "method": "chat",
            "latency_ms": latency_ms,
            "models": [],
            "message": f"上游返回 HTTP {r.status_code}：{r.text[:200]}",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "method": "chat",
            "latency_ms": int((asyncio.get_event_loop().time() - started) * 1000),
            "models": [],
            "message": f"网络不可达: {type(e).__name__} {e}（models 探测: {upstream_err}）",
        }


@router.put("/{provider_id}", response_model=ProviderConfigResponse)
async def update_provider(
    provider_id: str,
    req: ProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
) -> ProviderConfigResponse:
    raise _gone()


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str, db: AsyncSession = Depends(get_db), _: User = Depends(require_role("admin"))
) -> dict[str, object]:
    raise _gone()
