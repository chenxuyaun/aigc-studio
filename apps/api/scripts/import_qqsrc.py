"""导入 prompt.qqsrc.com 画廊数据到提示词库。

合规说明（对齐规格 §7.10）：
- 仅导入已获取的 JSON 元数据；不在本服务重新托管图片，封面直链其公开 R2 CDN。
- 保留来源站点(source_type=qqsrc)、来源链接、原作者署名(source_author)。
- 按 content_hash 去重，可重复执行（幂等）。

用法：
  uv run python scripts/import_qqsrc.py --data-dir /path/to/gallery_data [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.user import User
from sqlalchemy import select

SITE = "https://prompt.qqsrc.com"
IMG_BASE = "https://pub-54e40727ca014de0a7fecf608f7b0412.r2.dev"
# 兼容两套导出文件名：原始 qqsrc 分片 + 本地 downloads 画廊全量/twitter 分类。
DATA_FILES = [
    "prompts.part1.json",
    "prompts.part2.json",
    "prompts.part3.json",
    "prompts-twitter.json",
    # downloads 目录（grok2api 抓取的画廊全量与 twitter 分类）
    "all_prompts.json",
    "data_part1.json",
    "data_part2.json",
    "data_part3.json",
    "prompts-twitter-cat1.json",
    "prompts-twitter-cat2.json",
]


def _hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


async def _admin_id(db) -> str:  # type: ignore[no-untyped-def]
    admin = (
        await db.execute(select(User).where(User.role == "admin").limit(1))
    ).scalar_one_or_none()
    if admin is None:
        admin = User(
            username="admin",
            email="admin@aigc.local",
            password_hash=hash_password("admin123"),
            role="admin",
        )
        db.add(admin)
        await db.flush()
    return admin.id


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--limit", type=int, default=0, help="仅导入前 N 条（0=全部）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    items: list[dict[str, object]] = []
    for name in DATA_FILES:
        fp = data_dir / name
        if fp.exists():
            loaded = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                items.extend(loaded)
    if args.limit:
        items = items[: args.limit]
    print(f"读取 {len(items)} 条候选提示词")

    async with AsyncSessionLocal() as db:
        author_id = await _admin_id(db)

        # 现有分类与已导入 hash（幂等）。
        cat_rows = (await db.execute(select(PromptCategory))).scalars().all()
        cat_by_name: dict[str, str] = {c.name: c.id for c in cat_rows}
        seen_hashes: set[str] = {
            h for (h,) in (await db.execute(select(Prompt.content_hash))).all() if h
        }

        inserted = 0
        skipped = 0
        sort_base = len(cat_by_name)
        for it in items:
            prompt_text = str(it.get("prompt") or "").strip()
            title = str(it.get("title") or "").strip() or "未命名提示词"
            if not prompt_text:
                skipped += 1
                continue
            ch = _hash(prompt_text + "|" + title)
            if ch in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(ch)

            cat_name = str(it.get("category") or "").strip()
            category_id = None
            if cat_name:
                if cat_name not in cat_by_name:
                    new_cat = PromptCategory(name=cat_name, sort_order=sort_base + len(cat_by_name))
                    db.add(new_cat)
                    await db.flush()
                    cat_by_name[cat_name] = new_cat.id
                category_id = cat_by_name[cat_name]

            image = str(it.get("image") or "").lstrip("/")
            cover = f"{IMG_BASE}/{image}" if image else ""

            db.add(
                Prompt(
                    id=str(uuid.uuid4()),
                    title=title[:200],
                    content=prompt_text,
                    category_id=category_id,
                    prompt_type="image",
                    is_public=True,
                    author_id=author_id,
                    source_type="qqsrc",
                    cover_url=cover[:1000],
                    source_url=SITE,
                    source_author=str(it.get("author") or "")[:200],
                    content_hash=ch,
                )
            )
            inserted += 1
            if inserted % 500 == 0:
                await db.commit()
                print(f"  已提交 {inserted} 条…")

        await db.commit()
        print(f"完成：新增 {inserted}，跳过 {skipped}（重复/无内容）")


if __name__ == "__main__":
    asyncio.run(main())
