"""grok2api 账号健康度自动检测（celery beat 定时任务）。

- 登录 grok2api admin API（凭据：环境变量 GROK2API_ADMIN_USERNAME/PASSWORD，
  未配置时 fallback 读注册机 config.json）
- 分页拉取全部账号，判定废号（auth_status 非 active / 失败次数超阈值）
- 废号通过 batch 接口自动禁用（enabled=false），避免路由反复撞废号拖慢生成
- 结果写入 structlog（可在前端「运行日志」查看）

运行：worker 以 `-B`（beat）启动，schedule 见 celery_app.beat_schedule。
"""

from __future__ import annotations

import httpx
import structlog

from app.core.config import settings
from app.tasks.celery_app import celery_app

logger = structlog.get_logger("aigc.account_health")

ADMIN_BASE = "http://host.docker.internal:8000"
PAGE_SIZE = 100
# 失败次数 >= 该值视为废号（注册机新号通常为 0；连续 403/429 会累计）
FAILURE_THRESHOLD = 10


async def _admin_token(client: httpx.AsyncClient) -> str:
    """优先取环境变量；未配置时 fallback 读注册机 config.json（本机固定路径）。"""
    user = settings.GROK2API_ADMIN_USERNAME
    password = settings.GROK2API_ADMIN_PASSWORD
    if not user or not password:
        import json
        import os

        cfg = os.environ.get(
            "GROK_REGISTER_CONFIG",
            r"C:\Users\yuesh\.meituan-catpaw\5667331509\desk_default_workspace"
            r"\grok-register\GrokRegisterAgent\register\config.json",
        )
        try:
            with open(cfg, encoding="utf-8") as f:  # noqa: ASYNC230 - 配置读取极小，同步可接受
                c = json.load(f)
            user = str(c.get("grok2api_username") or "")
            password = str(c.get("grok2api_password") or "")
        except Exception:
            pass
    if not user or not password:
        raise RuntimeError("未配置 grok2api admin 凭据，跳过账号健康检查")
    r = await client.post(
        f"{ADMIN_BASE}/api/admin/v1/auth/login",
        json={"username": user, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["data"]["tokens"]["accessToken"]
    return str(token)


async def _fetch_all_accounts(
    client: httpx.AsyncClient, token: str
) -> list[dict[str, object]]:
    accounts: list[dict[str, object]] = []
    page = 1
    while True:
        r = await client.get(
            f"{ADMIN_BASE}/api/admin/v1/accounts",
            params={"page": page, "pageSize": PAGE_SIZE},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()["data"]
        items = data.get("items") or []
        accounts.extend(items)
        total = int(data.get("total") or 0)
        if page * PAGE_SIZE >= total or not items:
            break
        page += 1
    return accounts


async def _disable_accounts(
    client: httpx.AsyncClient, token: str, ids: list[str]
) -> int:
    if not ids:
        return 0
    r = await client.patch(
        f"{ADMIN_BASE}/api/admin/v1/accounts/batch",
        json={"ids": ids, "enabled": False, "provider": "grok_web"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if r.status_code >= 400:
        logger.warning(
            "account_health_disable_failed",
            status=r.status_code,
            body=str(r.text)[:200],
        )
        return 0
    return len(ids)


def run_account_health_check() -> dict[str, object]:
    """同步入口（celery task 调用）。"""
    import asyncio

    return asyncio.run(_check_once())


@celery_app.task(name="account_health_check")  # type: ignore[untyped-decorator]
def account_health_check() -> dict[str, object]:
    """Celery beat 定时任务：grok2api 账号健康巡检。"""
    try:
        return run_account_health_check()
    except Exception as exc:
        logger.warning("account_health_check_failed", error=str(exc)[:200])
        return {"error": str(exc)[:200]}


async def _check_once() -> dict[str, object]:
    async with httpx.AsyncClient(timeout=60) as client:
        token = await _admin_token(client)
        accounts = await _fetch_all_accounts(client, token)
        total = len(accounts)

        bad: list[dict[str, object]] = []
        for a in accounts:
            status = str(a.get("authStatus") or "")
            failures = int(str(a.get("failureCount") or 0))
            if status != "active" or failures >= FAILURE_THRESHOLD:
                bad.append(a)

        disable_ids = [str(a["id"]) for a in bad]
        disabled = await _disable_accounts(client, token, disable_ids)

        summary: dict[str, object] = {
            "total": total,
            "active": sum(
                1 for a in accounts if (a.get("authStatus") or "") == "active"
            ),
            "bad": len(bad),
            "disabled": disabled,
            "disabled_ids": disable_ids[:20],
        }
        logger.info("account_health_check", **summary)
        return summary
