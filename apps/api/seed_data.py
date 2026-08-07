# ruff: noqa: T201 E501
import asyncio
from typing import Any

from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.security import hash_password
from app.models.prompt import Prompt
from app.models.prompt_category import PromptCategory
from app.models.user import User
from app.models.workflow import Workflow
from sqlalchemy import select

# 推理小说工作坊预置模板（幂等，用户已存在时也会补充）
MYSTERY_WORKSHOP_TEMPLATE = {
    "nodes": [
        {
            "id": "n1",
            "type": "skill",
            "data": {
                "nodeType": "skill",
                "label": "案件设计",
                "params": {
                    "prompt": (
                        "你是推理小说主编。基于故事梗概设计完整案件方案，输出："
                        "1) 真相（唯一且自洽）2) 核心诡计（时间线/身份/密室等）"
                        "3) 误导设计（把读者引向的错误方向）4) 线索链（按 40-40-20："
                        "四成真线索、四成误导、两成氛围/红鲱鱼）5) 关键时间表（精确到分钟）。"
                        "直接输出方案文本。"
                    )
                },
            },
        },
        {
            "id": "n2",
            "type": "outline_gen",
            "data": {
                "nodeType": "outline_gen",
                "label": "八章大纲",
                "params": {"project_id": "{{project_id}}", "chapters": 8},
            },
        },
        {
            "id": "n3",
            "type": "chapter_gen",
            "data": {
                "nodeType": "chapter_gen",
                "label": "第一章",
                "params": {"project_id": "{{project_id}}", "chapter_no": 1},
            },
        },
        {
            "id": "n4",
            "type": "chapter_gen",
            "data": {
                "nodeType": "chapter_gen",
                "label": "第二章",
                "params": {"project_id": "{{project_id}}", "chapter_no": 2},
            },
        },
        {
            "id": "n5",
            "type": "chapter_gen",
            "data": {
                "nodeType": "chapter_gen",
                "label": "第三章",
                "params": {"project_id": "{{project_id}}", "chapter_no": 3},
            },
        },
        {
            "id": "n6",
            "type": "chapter_gen",
            "data": {
                "nodeType": "chapter_gen",
                "label": "第四章",
                "params": {"project_id": "{{project_id}}", "chapter_no": 4},
            },
        },
        {
            "id": "n7",
            "type": "skill",
            "data": {
                "nodeType": "skill",
                "label": "群聊审问场景",
                "params": {
                    "prompt": (
                        "你是推理小说编剧。基于前面的章节内容，生成一段多角色对质场景"
                        "（剧本格式：角色名：台词）：侦探当众审问主要嫌疑人，"
                        "证词互相矛盾，对话中暴露诡计的破绽（时间线/不在场证明/物证）。"
                        "输出完整对质场景。"
                    )
                },
            },
        },
        {
            "id": "n8",
            "type": "skill",
            "data": {
                "nodeType": "skill",
                "label": "逻辑校对",
                "params": {
                    "prompt": (
                        "你是推理小说校对。核对全书：1) 真相唯一性 2) 所有线索是否被解释"
                        "3) 是否有强行解释 4) 时间线是否自洽 5) 人物行为是否符合设定。"
                        "输出校验报告：通过项 + 问题清单（注明章节）+ 修改建议。"
                    )
                },
            },
        },
    ],
    "edges": [
        {"source": "n1", "target": "n2"},
        {"source": "n2", "target": "n3"},
        {"source": "n3", "target": "n4"},
        {"source": "n4", "target": "n5"},
        {"source": "n5", "target": "n6"},
        {"source": "n6", "target": "n7"},
        {"source": "n7", "target": "n8"},
    ],
}


async def seed() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME))
        if not result.scalar_one_or_none():
            admin = User(username=settings.INITIAL_ADMIN_USERNAME, email=settings.INITIAL_ADMIN_EMAIL, password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD), role="admin")
            db.add(admin)
            await db.flush()
            categories = [PromptCategory(name="文本生成", sort_order=1), PromptCategory(name="图片生成", sort_order=2), PromptCategory(name="视频生成", sort_order=3), PromptCategory(name="语音生成", sort_order=4), PromptCategory(name="教育场景", sort_order=5)]
            for cat in categories:
                db.add(cat)
            await db.flush()
            prompts_data = [
                ("文章写作助手", "请帮我写一篇关于{topic}的文章", "text", 0),
                ("图片生成提示词", "A beautiful {scene}, {style} style", "image", 1),
                ("视频脚本生成", "为以下内容生成短视频脚本：{content}", "video", 2),
                ("语音朗读文本", "请将以下内容转换为语音：{text}", "audio", 3),
                ("教学方案设计", "请为{subject}设计教学方案", "text", 4),
            ]
            for title, content, ptype, cat_idx in prompts_data:
                db.add(Prompt(title=title, content=content, prompt_type=ptype, author_id=admin.id, source_type="system_seed", category_id=categories[cat_idx].id))
            await db.commit()
            print("Seed created!")
        else:
            print("Admin exists, skipping seed.")
        await seed_workflow_templates(db)


async def seed_workflow_templates(db: Any | None = None) -> None:
    """幂等补充系统预置工作流模板（推理小说工作坊），任意库状态可重复执行。"""
    import json

    owns = db is not None
    if db is None:
        await init_db()
        db = AsyncSessionLocal()
    try:
        result = await db.execute(
            select(Workflow).where(
                Workflow.source_type == "system_seed",
                Workflow.name == "推理小说工作坊",
            )
        )
        if result.scalar_one_or_none() is not None:
            print("Workflow template exists, skip.")
            return
        admin = (
            await db.execute(select(User).where(User.role == "admin").limit(1))
        ).scalar_one_or_none()
        if admin is None:
            print("No admin user, skip workflow template.")
            return
        wf = Workflow(
            name="推理小说工作坊",
            description=(
                "一键跑完推理小说创作流水线：案件设计 → 八章大纲 → 逐章生成 → "
                "群聊审问场景 → 逻辑校对。使用前把各节点的 project_id 换成你的创作项目 ID。"
            ),
            graph=json.dumps(MYSTERY_WORKSHOP_TEMPLATE, ensure_ascii=False),
            workflow_type="sequential",
            is_public=True,
            author_id=str(admin.id),
            source_type="system_seed",
        )
        db.add(wf)
        await db.commit()
        print("Workflow template seeded: 推理小说工作坊")
    finally:
        if not owns:
            await db.close()


if __name__ == "__main__":
    asyncio.run(seed())
