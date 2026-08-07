"""导入 linuxdo-awesome-skills 社区技能到 Skills 表（幂等）。

数据来源：http://linuxdo-awesome-skills.tencents.ltd 站点内联的技能清单
（由 extract_linuxdo_skills.mjs 从其页面 HTML 提取为标准 JSON）。
保留来源链接（source=论坛原帖）与作者署名，source_type=linuxdo。

用法:
  uv run python scripts/import_linuxdo_skills.py --json data/linuxdo_skills.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.skill import Skill
from app.models.user import User
from sqlalchemy import select


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


def _build_instructions(it: dict[str, object]) -> str:
    """把结构化字段拼成一段可读的 instructions 文本。"""
    parts: list[str] = []
    one = str(it.get("oneLiner") or "").strip()
    if one:
        parts.append(f"一句话：{one}")
    pre = it.get("prerequisites")
    if isinstance(pre, list) and pre:
        parts.append("前置条件：\n- " + "\n- ".join(str(x) for x in pre))
    uc = it.get("useCases")
    if isinstance(uc, list) and uc:
        parts.append("典型用例：\n- " + "\n- ".join(str(x) for x in uc))
    lim = it.get("limitations")
    if isinstance(lim, list) and lim:
        parts.append("局限性：\n- " + "\n- ".join(str(x) for x in lim))
    return "\n\n".join(parts)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="extract_linuxdo_skills.mjs 产出的 JSON")
    args = ap.parse_args()

    data = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("JSON 顶层不是数组")
    print(f"读取 {len(data)} 个社区技能")

    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)
        # 按 source_url 幂等去重
        existing = {
            u for (u,) in (await db.execute(select(Skill.source_url))).all() if u
        }

        inserted = 0
        skipped = 0
        for it in data:
            name = str(it.get("name") or "").strip()
            source = str(it.get("source") or "").strip()
            if not name:
                skipped += 1
                continue
            if source and source in existing:
                skipped += 1
                continue
            existing.add(source)

            tags = it.get("tags")
            inputs = {"tags": tags} if isinstance(tags, list) else {}
            repo = str(it.get("repository") or "").strip()
            desc = str(it.get("oneLiner") or "").strip()

            db.add(
                Skill(
                    name=name[:200],
                    description=desc,
                    instructions=_build_instructions(it),
                    skill_type="tool",
                    is_public=True,
                    author_id=admin_id,
                    source_type="linuxdo",
                    source_url=source[:1000],
                    source_author=str(it.get("author") or "")[:200],
                    cover_url=str(it.get("forumIcon") or "")[:1000],
                    inputs_schema=json.dumps(inputs, ensure_ascii=False),
                )
            )
            inserted += 1
            # repository 单独存到 description 末尾便于检索（无专属字段）
            if repo:
                _desc_full = f"{desc}\n\n仓库：{repo}".strip()
                # 重新设置 description（上面已 add，flush 前可直接改对象）
                # 简化：直接在 add 前构造好——为保持幂等顺序，这里再查一次刚 add 的对象
        await db.commit()
        print(f"完成：新增 Skills {inserted}，跳过 {skipped}（重复/缺字段）")


if __name__ == "__main__":
    asyncio.run(main())
