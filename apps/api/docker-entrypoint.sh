#!/usr/bin/env bash
# API 容器启动入口：迁移 → 种子（仅空库）→ 启动 uvicorn。
# compose 用 CMD 覆盖为 ["bash", "docker-entrypoint.sh"] 时生效；
# 直接运行（systemd/本地）跳过此脚本，走 deploy 脚本执行 migrate/seed。
set -euo pipefail

echo "==> running alembic upgrade head"
alembic upgrade head

echo "==> seeding if empty"
python - <<'PY'
import asyncio
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.user import User
from seed_data import seed, seed_workflow_templates

async def main():
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    if count == 0:
        await seed()
        print("seeded initial data")
    else:
        print("users exist, skip seed")
        # 系统预置模板（推理小说工作坊）+ 内置 Hermes Provider（幂等补充，任意库状态可跑）
        await seed_workflow_templates()
        from seed_data import seed_hermes_provider

        async with AsyncSessionLocal() as db:
            await seed_hermes_provider(db)
        print("workflow templates ensured")

asyncio.run(main())
PY

echo "==> starting uvicorn"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
