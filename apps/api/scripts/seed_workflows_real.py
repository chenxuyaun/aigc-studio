"""工作流真实化：基于 prompts 分类创建真实工作流。

- 删除现有 source_type="curated" 的 5 个内置工作流（假数据）
- 基于 prompts 的 23 个分类，选 10 个大分类各生成一个工作流
- graph 节点引用该分类下真实 prompt 的 title
- workflow_type: sequential 或 parallel（多模型对比用 parallel）
- 幂等：按 name 去重

用法：
  python scripts/seed_workflows_real.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.core.database import AsyncSessionLocal
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_category import WorkflowCategory
from sqlalchemy import delete, select

# 选 10 个大分类 → (prompt_category_name, workflow_name, workflow_type, description)
TARGET_CATEGORIES = [
    ("平面设计", "平面设计海报出图流", "sequential",
     "从参考图选择到风格适配再到出图渲染的全流程，覆盖海报、banner、"
     "宣传图等平面设计场景，支持高分辨率输出与多版本对比。"),
    ("人像写真", "人像写真出图流", "sequential",
     "精选人像写真提示词，从参考构图到风格迁移再到高清出图，"
     "支持胶片质感、杂志风、自然光等多种人像风格。"),
    ("摄影纪实", "摄影纪实构图流", "sequential",
     "纪实摄影风格出图工作流，从场景描述到光影调色再到成片输出，"
     "还原街头、人文、新闻纪实的真实质感。"),
    ("动漫二次元", "二次元动漫生成流", "parallel",
     "二次元动漫风格多模型对比出图流，同一提示词并行调用多个模型，"
     "对比不同画风效果，适合动漫角色、场景设计。"),
    ("UI与界面", "UI界面设计流", "sequential",
     "UI/UX 界面设计出图工作流，从需求拆解到线框参考再到高保真渲染，"
     "覆盖 App 界面、网页设计、组件库等场景。"),
    ("动物自然", "动物自然摄影流", "sequential",
     "动物与自然主题摄影出图流，从物种特征描述到环境光影适配再到成片，"
     "还原野生动物、宠物、自然生态的真实细节。"),
    ("风景建筑", "风景建筑出图流", "parallel",
     "风景与建筑摄影多模型对比流，同一构图提示词并行生成，"
     "对比不同模型在建筑线条、光影氛围上的表现差异。"),
    ("游戏影视", "游戏影视概念流", "sequential",
     "游戏与影视概念设计出图流，从角色/场景概念到风格化渲染再到最终成图，"
     "支持赛博朋克、奇幻、写实等多种影视风格。"),
    ("插画艺术", "插画艺术创作流", "sequential",
     "插画艺术风格出图工作流，从灵感参考到画风选择再到插画生成，"
     "覆盖水彩、油画、扁平化、手绘等多种插画媒介。"),
    ("3D与产品", "3D产品渲染流", "sequential",
     "3D 产品渲染出图流，从产品参考到材质灯光设置再到高质量渲染，"
     "适合工业设计、产品展示、电商主图等场景。"),
]


async def _admin_id(db) -> str:
    admin = (
        await db.execute(select(User).where(User.role == "admin").limit(1))
    ).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("admin 用户不存在")
    return admin.id


async def _category_prompts(db, cat_id: str, limit: int) -> list[Prompt]:
    rows = (
        await db.execute(
            select(Prompt)
            .where(Prompt.category_id == cat_id)
            .where(Prompt.cover_url != "")
            .order_by(Prompt.use_count.desc(), Prompt.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def _build_sequential_graph(prompts: list[Prompt]) -> dict:
    """顺序流：参考图选择 → 真实prompt → 风格适配 → 出图渲染。"""
    nodes = [
        {"id": "1", "type": "skill", "name": "参考图选择"},
    ]
    edges = []
    prev_id = "1"
    for i, p in enumerate(prompts[:2], start=2):
        nodes.append({"id": str(i), "type": "prompt", "name": p.title[:40]})
        edges.append({"from": prev_id, "to": str(i)})
        prev_id = str(i)
    nodes.append({"id": str(len(nodes) + 1), "type": "skill", "name": "风格适配"})
    edges.append({"from": prev_id, "to": str(len(nodes))})
    prev_id = str(len(nodes))
    nodes.append({"id": str(len(nodes) + 1), "type": "agent", "name": "出图渲染"})
    edges.append({"from": prev_id, "to": str(len(nodes))})
    return {"nodes": nodes, "edges": edges}


def _build_parallel_graph(prompts: list[Prompt]) -> dict:
    """并行流：提示词输入 → 真实prompt → 模型A/模型B 并行出图。"""
    nodes = [
        {"id": "1", "type": "skill", "name": "提示词输入"},
    ]
    edges = []
    if prompts:
        nodes.append({"id": "2", "type": "prompt", "name": prompts[0].title[:40]})
        edges.append({"from": "1", "to": "2"})
        branch_from = "2"
    else:
        branch_from = "1"
    nodes.append({"id": "3", "type": "agent", "name": "模型A出图"})
    nodes.append({"id": "4", "type": "agent", "name": "模型B出图"})
    edges.append({"from": branch_from, "to": "3"})
    edges.append({"from": branch_from, "to": "4"})
    nodes.append({"id": "5", "type": "skill", "name": "效果对比"})
    edges.append({"from": "3", "to": "5"})
    edges.append({"from": "4", "to": "5"})
    return {"nodes": nodes, "edges": edges}


async def main() -> None:
    async with AsyncSessionLocal() as db:
        admin_id = await _admin_id(db)

        # 删除假的 curated 工作流
        deleted = await db.execute(
            delete(Workflow).where(Workflow.source_type == "curated")
        )
        await db.commit()
        print(f"删除 {deleted.rowcount} 个假 curated 工作流")

        # 加载 prompt 分类
        prompt_cats = {
            c.name: c.id for c in (
                await db.execute(select(PromptCategory))
            ).scalars().all()
        }
        # 加载/创建 workflow 分类
        wf_cats = {
            c.name: c for c in (
                await db.execute(select(WorkflowCategory))
            ).scalars().all()
        }
        # 已有工作流（按 name 幂等）
        existing_wf = {
            w.name: w for w in (
                await db.execute(
                    select(Workflow).where(Workflow.source_type == "real_prompt")
                )
            ).scalars().all()
        }

        created = 0
        for cat_name, wf_name, wf_type, desc in TARGET_CATEGORIES:
            pc_id = prompt_cats.get(cat_name)
            if pc_id is None:
                print(f"[跳过] 分类「{cat_name}」不存在")
                continue

            # 确保 workflow_category 存在
            wf_cat = wf_cats.get(cat_name)
            if wf_cat is None:
                wf_cat = WorkflowCategory(
                    id=str(uuid.uuid4()), name=cat_name, sort_order=len(wf_cats)
                )
                db.add(wf_cat)
                await db.flush()
                wf_cats[cat_name] = wf_cat

            prompts = await _category_prompts(db, pc_id, 3)
            if not prompts:
                print(f"[跳过] 分类「{cat_name}」无带封面的 prompt")
                continue

            graph_fn = _build_parallel_graph if wf_type == "parallel" else _build_sequential_graph
            graph = graph_fn(prompts)
            cover = prompts[0].cover_url

            wf = existing_wf.get(wf_name)
            if wf is None:
                wf = Workflow(
                    id=str(uuid.uuid4()),
                    name=wf_name,
                    description=desc,
                    graph=json.dumps(graph, ensure_ascii=False),
                    category_id=wf_cat.id,
                    workflow_type=wf_type,
                    is_public=True,
                    author_id=admin_id,
                    source_type="real_prompt",
                    cover_url=cover[:1000],
                    source_url=prompts[0].source_url[:1000] if prompts[0].source_url else "",
                    source_author=prompts[0].source_author[:200],
                )
                db.add(wf)
                created += 1
                print(f"[新建] {wf_name} ({wf_type}, {len(graph['nodes'])}节点)")
            else:
                # 更新已有工作流
                wf.description = desc
                wf.graph = json.dumps(graph, ensure_ascii=False)
                wf.category_id = wf_cat.id
                wf.cover_url = cover[:1000]
                print(f"[更新] {wf_name}")

        await db.commit()
        print(f"\n完成：新建 {created} 个真实工作流（共 {len(TARGET_CATEGORIES)} 目标分类）")


if __name__ == "__main__":
    asyncio.run(main())

