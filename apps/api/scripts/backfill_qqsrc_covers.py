"""为已导入的画廊提示词回填封面图（原站图床 CDN 直链）。

数据源：grok2api/downloads 下的 all_prompts.json / prompts-twitter.json。
映射：slug -> image 相对路径，cover_url = {IMG_BASE}/{image}。
注意：图床是 Cloudflare R2 公开桶（download.mjs 里的 IMG_BASE），
不要用 prompt.qqsrc.com 域名——它只服务 SPA 页面，图片路径会 404 fallback 成 HTML。
只处理 source_type in (qqsrc, twitter) 且 cover_url 为空的记录（幂等）。

用法：
  DATABASE_URL=mysql+aiomysql://... python scripts/backfill_qqsrc_covers.py \
    --dir D:/software/code/ideas/list/grok2api/downloads
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.models.prompt import Prompt
from sqlalchemy import select

IMG_BASE = "https://pub-54e40727ca014de0a7fecf608f7b0412.r2.dev"
BATCH = 1000


def _load_images(base: Path, filename: str) -> dict[str, str]:
    items = json.loads((base / filename).read_text(encoding="utf-8"))
    return {str(it.get("slug") or ""): str(it.get("image") or "") for it in items if it.get("image")}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="下载目录（含 all_prompts.json 等）")
    args = ap.parse_args()
    base = Path(args.dir)

    images: dict[str, str] = {}
    for fname in ("all_prompts.json", "prompts-twitter.json"):
        if (base / fname).exists():
            images.update(_load_images(base, fname))
    if not images:
        raise SystemExit("未找到图片映射数据")

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Prompt).where(
                    Prompt.source_type.in_(["qqsrc", "twitter"]),
                    (Prompt.cover_url == "") | (Prompt.cover_url.is_(None)),
                )
            )
        ).scalars().all()
        print(f"待回填: {len(rows)} 条")
        filled = skipped = 0
        for prompt in rows:
            slug = (prompt.source_url or "").split(":", 1)[-1]
            image = images.get(slug)
            if not image:
                skipped += 1
                continue
            prompt.cover_url = f"{IMG_BASE}/{image.lstrip('/')}"[:1000]
            filled += 1
            if filled % BATCH == 0:
                await db.commit()
                print(f"  ...已回填 {filled} 条")
        await db.commit()
        print(f"完成：回填 {filled} 条，跳过 {skipped} 条（无图映射）")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    asyncio.run(main())
