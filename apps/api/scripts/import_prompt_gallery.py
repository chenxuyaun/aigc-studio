"""导入 prompt.qqsrc.com 提示词画廊数据（用户从 grok2api/downloads 下载）。

数据源：
- all_prompts.json（13949 条，source_type=qqsrc）
- prompts-twitter.json（450 条，source_type=twitter）

映射：title→title；prompt→content；category→PromptCategory（按需创建）；
author→source_author；slug→source_url（幂等去重键，格式 qqsrc:<slug>）。
封面图（本地 images/ 3GB）暂不导入：cover_url 留空，后续按需接图片服务。

用法：
  DATABASE_URL=mysql+aiomysql://... python scripts/import_prompt_gallery.py \
    --dir D:/software/code/ideas/list/grok2api/downloads
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.user import User
from sqlalchemy import select

BATCH = 500


async def _admin_id(db) -> str:  # type: ignore[no-untyped-def]
    admin = (
        await db.execute(select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME))
    ).scalar_one_or_none()
    if admin is None:
        raise SystemExit("管理员不存在，请先初始化系统")
    return admin.id


async def _category_id(db, name: str, cache: dict[str, str]) -> str:  # type: ignore[no-untyped-def]
    if name in cache:
        return cache[name]
    cat = (
        await db.execute(select(PromptCategory).where(PromptCategory.name == name))
    ).scalar_one_or_none()
    if cat is None:
        cat = PromptCategory(name=name, sort_order=0)
        db.add(cat)
        await db.flush()
    cache[name] = cat.id
    return cat.id


async def import_file(db, path: Path, source_type: str, admin_id: str, cat_cache: dict[str, str], existing: set[str]) -> int:  # type: ignore[no-untyped-def]
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError(f"{path.name} 不是数组")
    created = 0
    batch: list[Prompt] = []
    for item in items:
        slug = str(item.get("slug") or item.get("id") or "")
        key = f"{source_type}:{slug}"
        if not slug or key in existing:
            continue
        title = str(item.get("title") or "未命名提示词")[:200]
        content = str(item.get("prompt") or item.get("content") or "")
        if not content.strip():
            continue
        category = str(item.get("category") or "").strip()
        cat_id = await _category_id(db, category, cat_cache) if category else None
        batch.append(
            Prompt(
                title=title,
                content=content,
                prompt_type="image",
                category_id=cat_id,
                is_public=True,
                author_id=admin_id,
                source_type=source_type,
                source_author=str(item.get("author") or "")[:200],
                source_url=key,
            )
        )
        existing.add(key)
        if len(batch) >= BATCH:
            db.add_all(batch)
            await db.commit()
            created += len(batch)
            batch = []
            print(f"  ...已导入 {created} 条")
    if batch:
        db.add_all(batch)
        await db.commit()
        created += len(batch)
    return created


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="下载目录（含 all_prompts.json 等）")
    args = ap.parse_args()
    base = Path(args.dir)
    gallery = base / "all_prompts.json"
    twitter = base / "prompts-twitter.json"

    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)
        existing = set(
            (
                await db.execute(
                    select(Prompt.source_url).where(
                        Prompt.source_type.in_(["qqsrc", "twitter"])
                    )
                )
            ).scalars().all()
        )
        cat_cache: dict[str, str] = {}
        total = 0
        if gallery.exists():
            n = await import_file(db, gallery, "qqsrc", admin_id, cat_cache, existing)
            print(f"画廊导入完成: {n} 条")
            total += n
        else:
            print(f"跳过：{gallery} 不存在")
        if twitter.exists():
            n = await import_file(db, twitter, "twitter", admin_id, cat_cache, existing)
            print(f"Twitter 导入完成: {n} 条")
            total += n
        else:
            print(f"跳过：{twitter} 不存在")
        print(f"合计新增 {total} 条提示词")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
