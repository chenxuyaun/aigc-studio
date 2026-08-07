"""技能/智能体分类立体化：补 category_id 与 inputs_schema 中的分类/标签信息。

- agents：已有 16 个分类，按 CSV Category 校验并补齐缺失分类
  （如 Infrastructure & DevOps、Writing & Prose Quality）
- skills：无 category_id 字段，将 CSV Category / linuxdo tags 写入 inputs_schema
  使数据立体化（category + sub_category + tags）

用法：
  python scripts/enrich_skills_agents.py
"""
from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.core.database import AsyncSessionLocal
from app.models.agent import Agent
from app.models.agent_category import AgentCategory
from app.models.skill import Skill
from sqlalchemy import select

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_csv() -> dict[str, dict]:
    """Link -> {category, sub_category, display_name, description}"""
    result: dict[str, dict] = {}
    fp = DATA_DIR / "awesome_claude_code.csv"
    with open(fp, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            link = (row.get("Link") or "").strip()
            if not link:
                continue
            result[link] = {
                "category": (row.get("Category") or "").strip(),
                "sub_category": (row.get("Sub-Category") or "").strip(),
                "display_name": (row.get("Display Name") or "").strip(),
                "description": (row.get("Description") or "").strip(),
            }
    return result


def _load_linuxdo() -> dict[str, dict]:
    """name -> {tags, repository, oneLiner}"""
    result: dict[str, dict] = {}
    fp = DATA_DIR / "linuxdo_skills.json"
    with open(fp, encoding="utf-8") as f:
        for item in json.load(f):
            name = (item.get("name") or "").strip()
            if not name:
                continue
            result[name] = {
                "tags": item.get("tags") or [],
                "repository": item.get("repository") or "",
                "oneLiner": item.get("oneLiner") or "",
            }
    return result


def _parse_schema(raw: str) -> dict:
    try:
        v = json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


async def main() -> None:
    import uuid

    from sqlalchemy import func

    csv_map = _load_csv()
    linuxdo_map = _load_linuxdo()
    print(f"CSV 条目: {len(csv_map)}, linuxdo 条目: {len(linuxdo_map)}")

    async with AsyncSessionLocal() as db:
        # ===== agents：校验 + 补齐缺失分类 =====
        agents = list((await db.execute(select(Agent))).scalars().all())
        existing_cats = {
            c.name: c for c in (await db.execute(select(AgentCategory))).scalars().all()
        }
        agent_updated = 0
        agent_cat_created = 0

        for ag in agents:
            info = csv_map.get((ag.source_url or "").strip())
            if not info or not info["category"]:
                continue
            csv_cat = info["category"]
            cat = existing_cats.get(csv_cat)
            if cat is None:
                cat = AgentCategory(
                    id=str(uuid.uuid4()), name=csv_cat, sort_order=len(existing_cats)
                )
                db.add(cat)
                await db.flush()
                existing_cats[csv_cat] = cat
                agent_cat_created += 1
                print(f"  [新建分类] {csv_cat}")
            if ag.category_id != cat.id:
                ag.category_id = cat.id
                agent_updated += 1

        # ===== skills：写入 inputs_schema 分类/标签 =====
        skills = list((await db.execute(select(Skill))).scalars().all())
        skill_updated = 0

        for sk in skills:
            schema = _parse_schema(sk.inputs_schema)
            changed = False

            if sk.source_type == "awesome-claude-code":
                info = csv_map.get((sk.source_url or "").strip())
                if info:
                    if info["category"]:
                        schema["category"] = info["category"]
                        changed = True
                    if info["sub_category"]:
                        schema["sub_category"] = info["sub_category"]
                        changed = True
                    if "tags" not in schema:
                        schema["tags"] = []
                        changed = True
            elif sk.source_type == "linuxdo":
                info = linuxdo_map.get((sk.name or "").strip())
                if info:
                    tags = info["tags"]
                    schema["tags"] = tags
                    if tags:
                        schema["category"] = tags[0]
                    changed = True

            if changed:
                sk.inputs_schema = json.dumps(schema, ensure_ascii=False)
                skill_updated += 1

        await db.commit()

        # ===== 统计 =====
        print("\n--- Agent 分类结果 ---")
        print(f"  分类总数: {len(existing_cats)} (新建 {agent_cat_created})")
        print(f"  更新分类的 agent: {agent_updated}")
        for cat_name, cat_obj in sorted(existing_cats.items()):
            cnt = (
                await db.execute(
                    select(func.count(Agent.id)).where(Agent.category_id == cat_obj.id)
                )
            ).scalar()
            print(f"    {cat_name}: {cnt}")

        with_cat = sum(
            1 for sk in skills if _parse_schema(sk.inputs_schema).get("category")
        )
        print("\n--- Skill 分类结果 ---")
        print(f"  更新 inputs_schema: {skill_updated} / {len(skills)}")
        print(f"  有 category 的 skill: {with_cat}")
        print("\n完成：agent 分类补齐 + skill inputs_schema 立体化")


if __name__ == "__main__":
    asyncio.run(main())

