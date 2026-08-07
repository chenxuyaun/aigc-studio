"""从公开目录抓取 Agent / Skill / Workflow 数据并入库（幂等）。

数据源（均为公开社区目录，保留来源链接与作者署名）：
- awesome-claude-code 资源表（https://github.com/hesreallyhim/awesome-claude-code）
  CSV 列：ID, Display Name, Category, Sub-Category, Link, Author Name, Author Link,
          Active, Date Added, Last Checked, Description, Stale
  按描述/名称关键词分类为 agent / skill；其余归为通用 agent。

工作流模板为内置精选（无外部依赖），保留署名标注 source_type=curated。

用法：
  uv run python scripts/fetch_public_agents.py
  uv run python scripts/fetch_public_agents.py --csv /path/to/file.csv --limit 50
  uv run python scripts/fetch_public_agents.py --remote   # 直接从 GitHub 拉取 CSV
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import urllib.request
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.agent import Agent
from app.models.agent_category import AgentCategory
from app.models.skill import Skill
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_category import WorkflowCategory
from sqlalchemy import select

CSV_URL = "https://raw.githubusercontent.com/hesreallyhim/awesome-claude-code/main/THE_RESOURCES_TABLE_NEW.csv"

# 关键词 → 类型：含「skill」归 skill；含 agent/bot/orchestr 归 agent；其余默认 agent。
_SKILL_HINTS = ("skill",)
_AGENT_HINTS = ("agent", "bot ", "bot,", "orchestr", "assistant")


def _classify(name: str, desc: str) -> str:
    blob = f"{name} {desc}".lower()
    if any(h in blob for h in _SKILL_HINTS):
        return "skill"
    if any(h in blob for h in _AGENT_HINTS):
        return "agent"
    return "agent"


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


def _load_csv(path: str | None, remote: bool, limit: int) -> list[dict[str, str]]:
    if remote:
        with urllib.request.urlopen(CSV_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        default = Path(__file__).resolve().parent.parent / "data" / "awesome_claude_code.csv"
        p = Path(path) if path else default
        if not p.exists():
            # 本地缺失则回退到远程拉取
            with urllib.request.urlopen(CSV_URL, timeout=30) as resp:
                text = resp.read().decode("utf-8")
            rows = list(csv.DictReader(io.StringIO(text)))
        else:
            with p.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
    rows = [
        r
        for r in rows
        if (r.get("Active") or "").upper() == "TRUE"
        and (r.get("Stale") or "").upper() != "TRUE"
    ]
    if limit:
        rows = rows[:limit]
    return rows


async def _seed_agents_skills(rows: list[dict[str, str]], admin_id: str) -> tuple[int, int, int]:
    """按分类幂等写入 agents / skills 表。返回 (agents, skills, skipped)。"""
    async with AsyncSessionLocal() as db:
        # 已存在的 source_url（幂等去重，按原始链接比较）
        agent_links = {u for (u,) in (await db.execute(select(Agent.source_url))).all() if u}
        skill_links = {u for (u,) in (await db.execute(select(Skill.source_url))).all() if u}

        # 分类
        cats = (await db.execute(select(AgentCategory))).scalars().all()
        cat_by_name: dict[str, str] = {c.name: c.id for c in cats}
        sort_base = len(cat_by_name)

        a_ins = s_ins = skipped = 0
        for r in rows:
            name = (r.get("Display Name") or "").strip()
            desc = (r.get("Description") or "").strip()
            link = (r.get("Link") or "").strip()
            author = (r.get("Author Name") or "").strip()
            cat_name = (r.get("Category") or "").strip()
            if not name or not link:
                skipped += 1
                continue

            kind = _classify(name, desc)
            if kind == "skill":
                if link in skill_links:
                    skipped += 1
                    continue
                skill_links.add(link)
                db.add(
                    Skill(
                        name=name[:200],
                        description=desc[:2000] if desc else "",
                        instructions=desc or f"参见来源：{link}",
                        skill_type="tool",
                        is_public=True,
                        author_id=admin_id,
                        source_type="awesome-claude-code",
                        source_url=link[:1000],
                        source_author=author[:200],
                        inputs_schema="{}",
                    )
                )
                s_ins += 1
            else:
                if link in agent_links:
                    skipped += 1
                    continue
                agent_links.add(link)
                category_id = None
                if cat_name and cat_name not in cat_by_name:
                    nc = AgentCategory(name=cat_name[:100], sort_order=sort_base + len(cat_by_name))
                    db.add(nc)
                    await db.flush()
                    cat_by_name[cat_name] = nc.id
                    sort_base += 1
                category_id = cat_by_name.get(cat_name) if cat_name else None
                db.add(
                    Agent(
                        name=name[:200],
                        description=desc[:2000] if desc else "",
                        system_prompt=desc or f"你是 {name}。参见：{link}",
                        agent_type="generic",
                        is_public=True,
                        author_id=admin_id,
                        source_type="awesome-claude-code",
                        source_url=link[:1000],
                        source_author=author[:200],
                        model="",
                        tools="[]",
                        category_id=category_id,
                    )
                )
                a_ins += 1
            if (a_ins + s_ins) % 50 == 0:
                await db.commit()
        await db.commit()
        return a_ins, s_ins, skipped


# 内置工作流模板（自包含，source_type=curated）。
_CURATED_WORKFLOWS: list[dict[str, object]] = [
    {
        "name": "内容创作流",
        "description": "选题 → 大纲 → 正文 → 润色，四步串行生成一篇图文并茂的文章。",
        "workflow_type": "sequential",
        "category": "内容创作",
        "graph": {
            "nodes": [
                {"id": "1", "type": "skill", "name": "选题"},
                {"id": "2", "type": "skill", "name": "大纲"},
                {"id": "3", "type": "agent", "name": "正文"},
                {"id": "4", "type": "skill", "name": "润色"},
            ],
            "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3"}, {"from": "3", "to": "4"}],
        },
    },
    {
        "name": "图片出图流",
        "description": "提示词生成 → 优化 → 图片生成 → 入素材库，闭环单图产出。",
        "workflow_type": "sequential",
        "category": "图像生成",
        "graph": {
            "nodes": [
                {"id": "1", "type": "skill", "name": "提示词生成"},
                {"id": "2", "type": "skill", "name": "提示词优化"},
                {"id": "3", "type": "agent", "name": "图片生成"},
            ],
            "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3"}],
        },
    },
    {
        "name": "短视频脚本流",
        "description": "选题 → 脚本分镜 → 旁白文案 → 语音合成，产出可拍摄脚本与配音。",
        "workflow_type": "sequential",
        "category": "视频生成",
        "graph": {
            "nodes": [
                {"id": "1", "type": "skill", "name": "选题"},
                {"id": "2", "type": "agent", "name": "脚本分镜"},
                {"id": "3", "type": "skill", "name": "旁白文案"},
                {"id": "4", "type": "agent", "name": "语音合成"},
            ],
            "edges": [
                {"from": "1", "to": "2"},
                {"from": "2", "to": "3"},
                {"from": "3", "to": "4"},
            ],
        },
    },
    {
        "name": "写真出图流",
        "description": "选写真参考图 → 提示词适配 → 图生图，差异化复用已有素材。",
        "workflow_type": "sequential",
        "category": "写真摄影",
        "graph": {
            "nodes": [
                {"id": "1", "type": "skill", "name": "参考图选择"},
                {"id": "2", "type": "agent", "name": "提示词适配"},
                {"id": "3", "type": "agent", "name": "图生图"},
            ],
            "edges": [{"from": "1", "to": "2"}, {"from": "2", "to": "3"}],
        },
    },
    {
        "name": "多模型对比流",
        "description": "同一提示词并行调用多个模型，汇总对比输出质量，择优入库。",
        "workflow_type": "parallel",
        "category": "模型评测",
        "graph": {
            "nodes": [
                {"id": "1", "type": "agent", "name": "模型A"},
                {"id": "2", "type": "agent", "name": "模型B"},
                {"id": "3", "type": "skill", "name": "汇总对比"},
            ],
            "edges": [{"from": "1", "to": "3"}, {"from": "2", "to": "3"}],
        },
    },
]


async def _seed_workflows(admin_id: str) -> int:
    async with AsyncSessionLocal() as db:
        existing = {w.name for w in (await db.execute(select(Workflow))).scalars().all()}
        cats = (await db.execute(select(WorkflowCategory))).scalars().all()
        cat_by_name = {c.name: c.id for c in cats}
        sort_base = len(cat_by_name)

        ins = 0
        for tpl in _CURATED_WORKFLOWS:
            name = tpl["name"]
            if name in existing:
                continue
            cat_name = tpl["category"]
            if cat_name and cat_name not in cat_by_name:
                nc = WorkflowCategory(name=cat_name[:100], sort_order=sort_base + len(cat_by_name))
                db.add(nc)
                await db.flush()
                cat_by_name[cat_name] = nc.id
                sort_base += 1
            db.add(
                Workflow(
                    name=name[:200],
                    description=tpl["description"],
                    graph=json.dumps(tpl["graph"], ensure_ascii=False),
                    workflow_type=tpl["workflow_type"],
                    is_public=True,
                    author_id=admin_id,
                    source_type="curated",
                    category_id=cat_by_name.get(cat_name) if cat_name else None,
                )
            )
            ins += 1
        await db.commit()
        return ins


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="", help="本地 CSV 路径；默认远程拉取")
    ap.add_argument("--remote", action="store_true", help="强制从 GitHub 拉取 CSV")
    ap.add_argument("--limit", type=int, default=0, help="仅导入前 N 条（0=全部）")
    ap.add_argument("--skip-workflows", action="store_true", help="不导入内置工作流模板")
    args = ap.parse_args()

    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)

    rows = _load_csv(args.csv or None, args.remote, args.limit)
    print(f"读取 {len(rows)} 条有效公开目录条目")
    a, s, sk = await _seed_agents_skills(rows, admin_id)
    print(f"Agents: 新增 {a}，Skills: 新增 {s}，跳过 {sk}（重复/缺字段）")

    if not args.skip_workflows:
        w = await _seed_workflows(admin_id)
        print(f"Workflows: 新增 {w}（内置精选）")


if __name__ == "__main__":
    asyncio.run(main())
