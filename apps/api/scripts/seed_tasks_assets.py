"""任务中心 + 素材库真实历史数据种子。

- 从 prompts 表随机取 60 条真实 prompt 作为任务 params
- 生成 60 个 GenerationTask，status 分布 succeeded70/failed15/queued5/running5/cancelled5
- succeeded 的任务创建对应 Asset 记录（指向已有写真图或 mock 产物）
- failed 的用真实失败原因
- 幂等：先删 params 含 '"seed":true' 的旧任务再插

用法：
  python scripts/seed_tasks_assets.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.core.database import AsyncSessionLocal
from app.models.asset import Asset
from app.models.generation_task import GenerationTask
from app.models.photo import Photo
from app.models.prompt import Prompt
from app.models.user import User
from sqlalchemy import delete, func, select, text

random.seed(42)
TOTAL_TASKS = 60

# 状态分布（百分比）
STATUS_DIST = [
    ("succeeded", 0.70),
    ("failed", 0.15),
    ("queued", 0.05),
    ("running", 0.05),
    ("cancelled", 0.05),
]

# task_type 分布
TYPE_DIST = [
    ("image", 0.70),
    ("text", 0.15),
    ("video", 0.08),
    ("audio", 0.07),
]

# 真实模型名
MODELS = {
    "image": ["dall-e-3", "stable-diffusion-xl", "flux-pro-1.1", "midjourney-v6", "mock"],
    "text": ["gpt-4o", "claude-3.5-sonnet", "deepseek-v3", "mock"],
    "video": ["sora", "runway-gen3-alpha", "kling-v1.5", "mock"],
    "audio": ["eleven-multilingual-v2", "suno-v3.5", "mock"],
}

# 真实失败原因
FAIL_REASONS = [
    "模型推理超时（120s），请重试或降低分辨率",
    "内容审核拦截：检测到敏感关键词，请修改后重新提交",
    "配额不足：今日生成次数已达上限，请明日再试或升级套餐",
    "上游 API 返回 429，触发限流，请稍后重试",
    "图片尺寸超出限制：最大支持 2048x2048，当前 4096x4096",
    "模型服务暂时不可用（503），请稍后重试",
    "提示词长度超限：最大 8000 字符，当前 12450 字符",
    "负面提示词与正向提示词冲突，导致生成失败",
]



def _pick_distribution(dist, n):
    """按分布生成 n 个值的列表。"""
    result = []
    for val, pct in dist:
        result.extend([val] * round(n * pct))
    while len(result) < n:
        result.append(dist[0][0])
    random.shuffle(result)
    return result[:n]


def _random_datetime(days_back=30):
    now = datetime.now(UTC)
    return now - timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


async def _admin_id(db) -> str:
    admin = (
        await db.execute(select(User).where(User.role == "admin").limit(1))
    ).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("admin 用户不存在")
    return admin.id


async def _sample_prompts(db, n: int) -> list[Prompt]:
    # 取带内容的 prompt，优先 image 类型，混入少量 text
    image_rows = (
        await db.execute(
            select(Prompt).where(Prompt.prompt_type == "image").order_by(func.random()).limit(n)
        )
    ).scalars().all()
    text_rows = (
        await db.execute(
            select(Prompt).where(Prompt.prompt_type == "text").order_by(func.random()).limit(5)
        )
    ).scalars().all()
    pool = list(text_rows) + list(image_rows)
    random.shuffle(pool)
    return pool[:n]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)

        # 幂等：删除旧的 seed 任务及其关联 asset
        # json.dumps 会在冒号后产生空格："seed": true，故用 '%"seed"%' 宽匹配
        old_ids = [
            r[0] for r in (
                await db.execute(
                    select(GenerationTask.id).where(
                        GenerationTask.params.like('%"seed"%')
                    )
                )
            ).all()
        ]
        if old_ids:
            await db.execute(delete(Asset).where(Asset.task_id.in_(old_ids)))
            await db.execute(delete(GenerationTask).where(GenerationTask.id.in_(old_ids)))
            await db.commit()
            print(f"清理旧 seed 任务 {len(old_ids)} 条")

        prompts = await _sample_prompts(db, TOTAL_TASKS)
        print(f"采样 {len(prompts)} 条真实 prompt")
        statuses = _pick_distribution(STATUS_DIST, TOTAL_TASKS)
        types = _pick_distribution(TYPE_DIST, TOTAL_TASKS)

        photos = list(
            (await db.execute(
                select(Photo).order_by(Photo.created_at.desc()).limit(40)
            )).scalars().all()
        )
        photo_idx = 0
        created = 0

        for i in range(TOTAL_TASKS):
            p = prompts[i % len(prompts)]
            task_type = types[i]
            status = statuses[i]
            model = random.choice(MODELS[task_type])
            created_at = _random_datetime(30)

            params = {"seed": True, "prompt": p.content[:2000], "title": p.title,
                      "model": model, "source_prompt_id": p.id}
            if task_type == "image":
                params.update({"width": random.choice([512, 768, 1024, 1536]),
                    "height": random.choice([512, 768, 1024, 1536]),
                    "num_images": random.choice([1, 1, 1, 2, 4]),
                    "negative_prompt": "", "steps": random.choice([20, 28, 30, 40]),
                    "cfg_scale": round(random.uniform(5.0, 9.0), 1)})
            elif task_type == "video":
                params.update({"duration": random.choice([5, 10, 15]), "fps": 24,
                    "resolution": random.choice(["720p", "1080p"]),
                    "reference_prompt_id": p.id})
            elif task_type == "audio":
                params.update({"voice": random.choice(["alloy", "echo", "fable", "onyx"]),
                    "speed": round(random.uniform(0.8, 1.2), 1),
                    "reference_text": p.content[:500]})
            elif task_type == "text":
                params.update({"max_tokens": random.choice([1024, 2048, 4096]),
                    "temperature": round(random.uniform(0.3, 1.2), 2),
                    "system_prompt": "你是一位专业的创意写作助手。"})

            progress = (100 if status == "succeeded" else
                        random.randint(30, 80) if status == "running" else
                        0 if status == "queued" else
                        random.randint(50, 90) if status == "failed" else
                        random.randint(10, 60))

            completed_at = None
            if status in ("succeeded", "failed", "cancelled"):
                completed_at = created_at + timedelta(seconds=random.randint(5, 300))
            error_message = random.choice(FAIL_REASONS) if status == "failed" else ""

            # result + asset
            result = ""
            asset_id = None
            if status == "succeeded":
                if task_type == "text":
                    result = json.dumps({"text": f"基于「{p.title}」生成的创意文本内容"
                                                   "（已成功生成，共 832 字）"}, ensure_ascii=False)
                elif photos:
                    ph = photos[photo_idx % len(photos)]
                    photo_idx += 1
                    asset = Asset(
                        id=str(uuid.uuid4()), filename=ph.filename,
                        storage_key=ph.storage_key, storage_backend="local",
                        mime_type=ph.mime_type, size_bytes=ph.size_bytes,
                        sha256=hashlib.sha256(
                            (ph.storage_key + str(created_at)).encode()).hexdigest(),
                        user_id=admin_id,
                    )
                    db.add(asset)
                    await db.flush()
                    asset_id = asset.id
                    result = json.dumps({"asset_id": asset_id, "width": ph.width,
                        "height": ph.height, "url": f"/storage/{ph.storage_key}"},
                        ensure_ascii=False)

            task = GenerationTask(
                id=str(uuid.uuid4()), task_type=task_type, status=status,
                progress=progress, params=json.dumps(params, ensure_ascii=False),
                result=result, model=model, error_message=error_message,
                user_id=admin_id, created_at=created_at, completed_at=completed_at,
            )
            db.add(task)
            if asset_id:
                asset.task_id = task.id
            await db.flush()
            created += 1
            if created % 20 == 0:
                await db.commit()
                print(f"  已创建 {created} 条任务…")

        await db.commit()
        print("\n--- 任务状态分布 ---")
        for r in (
            await db.execute(
                text("SELECT status, COUNT(*) FROM generation_tasks GROUP BY status ORDER BY status")
            )
        ).all():
            print(f"  {r[0]}: {r[1]}")
        print(f"\n完成：共创建 {created} 条任务（含 seed 标记，可重跑）")


if __name__ == "__main__":
    asyncio.run(main())
