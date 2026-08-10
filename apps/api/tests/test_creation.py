"""创作工作台 API：主题 → AI 选角 → 建组（AI 导演工作室）。"""

from __future__ import annotations

import json

import pytest
from app.models.roleplay_character import RoleplayCharacter
from app.models.roleplay_chat import RoleplayChat
from app.models.roleplay_group import RoleplayGroup, RoleplayGroupMember
from app.models.text_document import TextDocument
from sqlalchemy import select

from tests.conftest import TestingSessionLocal

_FIXED_PLAN = {
    "group_name": "夜食缘",
    "genre": "都市温情",
    "logline": "深夜食堂里的都市温情故事。",
    "characters": [
        {
            "name": "小雅",
            "role": "店主",
            "description": "三十岁女店主，温柔但藏着执念。",
            "personality": "温柔体贴、轻声细语",
            "first_mes": "欢迎来到夜食缘，进来坐坐。",
        },
        {
            "name": "老赵",
            "role": "常客",
            "description": "五十岁退休厨师，爱点评。",
            "personality": "直爽、爱唠嗑",
            "first_mes": "老板，老规矩，一碗牛肉面。",
        },
    ],
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _count(model) -> int:
    async with TestingSessionLocal() as db:
        return (await db.execute(select(model))).scalars().all().__len__()


@pytest.mark.asyncio
async def test_plan_returns_ai_cast(client, user_token, monkeypatch) -> None:
    """plan：mock AI 选角，返回角色方案 JSON。"""
    async def fake_plan(db, theme: str, user_id: str | None = None):
        return dict(_FIXED_PLAN)
    monkeypatch.setattr("app.services.creation_service.plan_project", fake_plan)
    r = await client.post(
        "/api/v1/creation/plan",
        headers=_headers(user_token),
        json={"theme": "深夜食堂"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["group_name"] == "夜食缘"
    assert len(data["characters"]) == 2
    assert data["characters"][0]["role"] == "店主"


_FIXED_SCRIPT = {
    "title": "夜食缘",
    "genre": "都市温情",
    "logline": "深夜食堂里的都市温情故事。",
    "acts": [
        {
            "act_no": 1,
            "act_title": "开张",
            "act_summary": "女店主深夜开张，老赵与各色客人登场。",
            "scenes": [
                {
                    "scene_no": 1,
                    "location": "夜食缘·店内·深夜",
                    "characters": "小雅,老赵",
                    "beat": "小雅开张，老赵点面，两人闲聊带出店里规矩。",
                    "dialogue_hint": "老赵：老板，老规矩，一碗牛肉面，多加香菜。",
                }
            ],
        }
    ],
    "finale_hint": "小店成为街坊的精神寄托。",
}


@pytest.mark.asyncio
async def test_script_returns_act_outline(client, user_token, monkeypatch) -> None:
    """script：mock 编剧，返回分幕大纲 JSON。"""
    async def fake_script(db, *, theme: str, plan: dict | None = None, variants: int = 1):
        assert plan is not None  # 前端会带角色方案
        return dict(_FIXED_SCRIPT)
    monkeypatch.setattr("app.services.creation_service.script_project", fake_script)
    r = await client.post(
        "/api/v1/creation/script",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": _FIXED_PLAN},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "夜食缘"
    assert data["acts"][0]["act_title"] == "开张"
    assert data["acts"][0]["scenes"][0]["dialogue_hint"].startswith("老赵")
    assert data["finale_hint"]


@pytest.mark.asyncio
async def test_script_without_plan(client, user_token, monkeypatch) -> None:
    """script 不带角色方案也可（AI 自创角色）。"""
    async def fake_script(db, *, theme: str, plan: dict | None = None, variants: int = 1):
        assert plan is None
        return dict(_FIXED_SCRIPT)
    monkeypatch.setattr("app.services.creation_service.script_project", fake_script)
    r = await client.post(
        "/api/v1/creation/script",
        headers=_headers(user_token),
        json={"theme": "深夜食堂"},
    )
    assert r.status_code == 200
    assert r.json()["acts"]


@pytest.mark.asyncio
async def test_setup_creates_chars_and_group(client, user_token) -> None:
    """setup：按方案建角色卡 + 自动建群 + 群主入群。"""
    before_chars = await _count(RoleplayCharacter)
    before_groups = await _count(RoleplayGroup)
    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": _FIXED_PLAN},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["chat_id"]
    assert data["group_name"] == "夜食缘"
    assert len(data["characters"]) == 2

    async with TestingSessionLocal() as db:
        chat = await db.get(RoleplayChat, data["chat_id"])
        assert chat is not None
        assert chat.is_room is True
        assert chat.group is True
        assert json.loads(chat.character_asset_ids) == [
            c["asset_id"] for c in data["characters"]
        ]
        grp = await db.get(RoleplayGroup, data["chat_id"])
        assert grp is not None
        assert grp.name == "夜食缘"
        member = (
            await db.execute(
                select(RoleplayGroupMember).where(
                    RoleplayGroupMember.group_id == data["chat_id"]
                )
            )
        ).scalars().all()
        assert len(member) == 1  # 群主
    assert await _count(RoleplayCharacter) == before_chars + 2
    assert await _count(RoleplayGroup) == before_groups + 1


@pytest.mark.asyncio
async def test_setup_without_plan_calls_ai(client, user_token, monkeypatch) -> None:
    """setup 不传 plan → 自动调 AI 选角。"""
    called: list[str] = []

    async def fake_plan(db, theme: str, user_id: str | None = None):
        called.append(theme)
        return dict(_FIXED_PLAN)

    monkeypatch.setattr("app.services.creation_service.plan_project", fake_plan)
    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂"},
    )
    assert r.status_code == 200
    assert called == ["深夜食堂"]
    assert r.json()["chat_id"]


@pytest.mark.asyncio
async def test_setup_bad_plan_rejected(client, user_token) -> None:
    """方案无效（无角色）→ 不建任何东西。"""
    before_groups = await _count(RoleplayGroup)
    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": {"group_name": "x", "characters": []}},
    )
    assert r.status_code == 200
    assert "error" in r.json()
    assert await _count(RoleplayGroup) == before_groups


@pytest.mark.asyncio
async def test_setup_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.post(
        "/api/v1/creation/setup", json={"theme": "深夜食堂"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_setup_reuses_same_name_characters(client, user_token) -> None:
    """去重复用：已有同名角色卡 → 直接复用（不新建、数量不增）。"""
    # 第一次：建 2 个角色（小雅/老赵）
    r1 = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": _FIXED_PLAN},
    )
    assert r1.status_code == 200
    first = r1.json()
    assert [c["reused"] for c in first["characters"]] == [False, False]
    assert first["reused_count"] == 0
    first_ids = {c["name"]: c["asset_id"] for c in first["characters"]}

    chars_before = await _count(RoleplayCharacter)
    groups_before = await _count(RoleplayGroup)

    # 第二次：同名方案 → 全部复用
    r2 = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": _FIXED_PLAN},
    )
    assert r2.status_code == 200
    second = r2.json()
    assert [c["reused"] for c in second["characters"]] == [True, True]
    assert second["reused_count"] == 2
    for c in second["characters"]:
        assert c["asset_id"] == first_ids[c["name"]]

    # 角色卡数量不变（没有重复创建），只新增了群
    assert await _count(RoleplayCharacter) == chars_before
    assert await _count(RoleplayGroup) == groups_before + 1


@pytest.mark.asyncio
async def test_setup_reuses_shared_characters(client, user_token) -> None:
    """共享角色卡（is_shared）也可被复用。"""
    async with TestingSessionLocal() as db:
        db.add(
            RoleplayCharacter(
                asset_id="shared-char-1", user_id="someone-else",
                name="小雅", description="共享卡", personality="温柔",
                is_shared=True,
            )
        )
        await db.commit()

    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": _FIXED_PLAN},
    )
    assert r.status_code == 200
    data = r.json()
    reused = [c for c in data["characters"] if c["reused"]]
    assert any(c["name"] == "小雅" and c["asset_id"] == "shared-char-1" for c in reused)


@pytest.mark.asyncio
async def test_plan_retrieves_theme_materials(client, user_token, monkeypatch) -> None:
    """plan：知识库有相关文档 → 资料摘要并入 prompt（AI 选角参考）。"""
    from app.models.user import User
    from app.providers.base import TextResult
    from app.services.provider_resolver import ResolvedTextProvider

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            TextDocument(
                title="深夜食堂设定",
                content="深夜食堂位于巷尾，店主小雅擅长暖胃的炖菜，"
                        "常客有失业程序员、单亲妈妈、退休厨师。",
                user_id=u.id,
            )
        )
        await db.commit()

    class _RecordingProvider:
        def __init__(self) -> None:
            self.prompt = ""

        async def generate(self, prompt: str, model: str = "", **kwargs):
            self.prompt = prompt
            return TextResult(
                content=json.dumps(_FIXED_PLAN, ensure_ascii=False),
                model=model, provider="fake",
            )

    rec = _RecordingProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            rec, "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr(
        "app.services.creation_service.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/creation/plan",
        headers=_headers(user_token),
        json={"theme": "深夜食堂"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["group_name"] == "夜食缘"
    assert data["materials_hits"] is True
    # prompt 里带上了知识库检索到的资料（文档标题 + 内容要点）
    assert "深夜食堂设定" in rec.prompt
    assert "小雅" in rec.prompt


@pytest.mark.asyncio
async def test_plan_retrieves_character_pool(client, user_token, monkeypatch) -> None:
    """plan：已有角色卡与主题相关 → 角色池并入 prompt（AI 可直接引用复用）。"""
    from app.models.user import User
    from app.providers.base import TextResult
    from app.services.provider_resolver import ResolvedTextProvider

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            RoleplayCharacter(
                asset_id="pool-char-1", user_id=u.id,
                name="小雅", description="深夜食堂女店主，擅长炖菜",
                personality="温柔体贴",
            )
        )
        await db.commit()

    class _RecordingProvider:
        def __init__(self) -> None:
            self.prompt = ""

        async def generate(self, prompt: str, model: str = "", **kwargs):
            self.prompt = prompt
            return TextResult(
                content=json.dumps(_FIXED_PLAN, ensure_ascii=False),
                model=model, provider="fake",
            )

    rec = _RecordingProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            rec, "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr(
        "app.services.creation_service.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/creation/plan",
        headers=_headers(user_token),
        json={"theme": "深夜食堂"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["pool_hits"] >= 1
    assert data["pool"][0]["asset_id"] == "pool-char-1"
    # prompt 含角色池（asset_id + 角色简介）
    assert "已有角色池" in rec.prompt
    assert "pool-char-1" in rec.prompt
    assert "小雅" in rec.prompt


@pytest.mark.asyncio
async def test_setup_uses_asset_id_from_plan(client, user_token) -> None:
    """方案角色带 asset_id（AI 从角色池引用）→ 直接复用该角色卡，不新建。"""
    from app.models.user import User

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        db.add(
            RoleplayCharacter(
                asset_id="pool-char-2", user_id=u.id,
                name="小雅", description="深夜食堂女店主",
                personality="温柔",
            )
        )
        await db.commit()

    plan = {
        "group_name": "夜食缘",
        "genre": "都市温情",
        "logline": "x",
        "characters": [
            {
                "name": "小雅", "role": "店主",
                "description": "深夜食堂女店主", "personality": "温柔",
                "first_mes": "欢迎光临。",
                "source": "existing", "asset_id": "pool-char-2",
            },
            {
                "name": "新客", "role": "常客",
                "description": "新来的常客", "personality": "直爽",
                "first_mes": "老板，来碗面。",
                "source": "new",
            },
        ],
    }
    chars_before = await _count(RoleplayCharacter)
    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": plan},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["reused_count"] == 1
    by_name_map = {c["name"]: c for c in data["characters"]}
    assert by_name_map["小雅"]["asset_id"] == "pool-char-2"
    assert by_name_map["小雅"]["reused"] is True
    # 只新建了 1 个角色（新客），小雅未重复创建
    assert await _count(RoleplayCharacter) == chars_before + 1


@pytest.mark.asyncio
async def test_publish_creates_story_project(client, user_token, monkeypatch) -> None:
    """群演出 → 剧本存入创作工作室（story 项目 + 章节正文）。"""
    from app.models.story_chapter import StoryChapter
    from app.models.story_project import StoryProject
    from app.models.user import User
    from app.providers.base import TextResult
    from app.services import sessions as _sessions
    from app.services.group_service import create_group as _create_group
    from app.services.provider_resolver import ResolvedTextProvider

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        chat = await _sessions.create_chat(
            db, u.id, title="梨园谜案", character_asset_ids=[],
            group=True, is_room=True,
        )
        await _create_group(db, owner_id=u.id, chat_id=chat.id, name="梨园谜案", description="")
        await _sessions.append_message(
            db, chat, {"role": "user", "content": "（第1场）子衿为墨尘裹伤。"}
        )
        await _sessions.append_message(
            db, chat, {"role": "assistant", "content": "子衿：雨声凄凉，却掩不住我心中的动容。"}
        )
        await db.commit()
        chat_id = chat.id

    class _RecordingProvider:
        async def generate(self, prompt: str, model: str = "", **kwargs):
            self.prompt = prompt
            return TextResult(
                content="**第一幕**\n雨夜梨园·后院\n子衿为墨尘裹伤……\n【子衿】雨声凄凉，却掩不住我心中的动容。",
                model=model, provider="fake",
            )

    rec = _RecordingProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            rec, "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr(
        "app.services.creation_service.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/creation/publish",
        headers=_headers(user_token),
        json={"chat_id": chat_id},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["project_id"]
    assert data["chapter_id"]
    assert data["project_title"] == "梨园谜案"
    # 演出记录进了整理 prompt
    assert "子衿为墨尘裹伤" in rec.prompt

    async with TestingSessionLocal() as db:
        proj = await db.get(StoryProject, data["project_id"])
        assert proj is not None
        owner = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        assert proj.user_id == owner.id
        chap = await db.get(StoryChapter, data["chapter_id"])
        assert chap is not None
        assert "第一幕" in chap.content
        assert "子衿" in chap.content


@pytest.mark.asyncio
async def test_publish_empty_group_rejected(client, user_token) -> None:
    """群无演出记录 → error，不建项目。"""
    from app.models.story_project import StoryProject
    from app.models.user import User
    from app.services import sessions as _sessions
    from app.services.group_service import create_group as _create_group

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        chat = await _sessions.create_chat(
            db, u.id, title="空群", character_asset_ids=[],
            group=True, is_room=True,
        )
        await _create_group(db, owner_id=u.id, chat_id=chat.id, name="空群", description="")
        await db.commit()
        chat_id = chat.id

    before = await _count(StoryProject)
    r = await client.post(
        "/api/v1/creation/publish",
        headers=_headers(user_token),
        json={"chat_id": chat_id},
    )
    assert r.status_code == 200
    assert "error" in r.json()
    assert await _count(StoryProject) == before


@pytest.mark.asyncio
async def test_script_variants_returns_multiple(client, user_token, monkeypatch) -> None:
    """variants=3 → 并行生成 3 版对比。"""
    calls: list[int] = []

    async def fake_once(db, *, theme: str, plan: dict | None):
        calls.append(1)
        return dict(_FIXED_SCRIPT)

    monkeypatch.setattr("app.services.creation_service._script_once", fake_once)
    from app.services import creation_service

    async with TestingSessionLocal() as db:
        result = await creation_service.script_project(
            db, theme="x", plan=None, variants=3
        )
    assert "variants" in result
    assert len(result["variants"]) == 3
    assert len(calls) == 3  # 并行调用了 3 次生成


@pytest.mark.asyncio
async def test_review_returns_score_and_advice(client, user_token, monkeypatch) -> None:
    """评审：mock AI 返回评分/亮点/弱点/建议。"""
    from app.providers.base import TextResult
    from app.services.provider_resolver import ResolvedTextProvider

    review_json = json.dumps(
        {
            "score": 7,
            "strengths": ["第一幕冲突引入快"],
            "weaknesses": ["第二幕反派动机不足"],
            "suggestions": ["给反派加一段往事"],
        },
        ensure_ascii=False,
    )

    class _RecordingProvider:
        def __init__(self) -> None:
            self.prompt = ""

        async def generate(self, prompt: str, model: str = "", **kwargs):
            self.prompt = prompt
            return TextResult(content=review_json, model=model, provider="fake")

    rec = _RecordingProvider()

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            rec, "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr(
        "app.services.creation_service.resolve_text_provider", fake_resolver
    )
    r = await client.post(
        "/api/v1/creation/review",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "script": _FIXED_SCRIPT},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["score"] == 7
    assert data["strengths"][0] == "第一幕冲突引入快"
    assert "反派动机不足" in data["weaknesses"][0]
    # 评审 prompt 带上了大纲内容
    assert "夜食缘" in rec.prompt


@pytest.mark.asyncio
async def test_setup_invalid_asset_id_falls_back(client, user_token) -> None:
    """asset_id 无效（不存在/非本人）→ 兜底新建，不报错。"""
    plan = {
        "group_name": "夜食缘",
        "genre": "都市温情",
        "logline": "x",
        "characters": [
            {
                "name": "小雅", "role": "店主",
                "description": "d", "personality": "p",
                "first_mes": "f",
                "source": "existing", "asset_id": "no-such-asset",
            },
        ],
    }
    chars_before = await _count(RoleplayCharacter)
    r = await client.post(
        "/api/v1/creation/setup",
        headers=_headers(user_token),
        json={"theme": "深夜食堂", "plan": plan},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["reused_count"] == 0
    assert data["characters"][0]["reused"] is False
    assert await _count(RoleplayCharacter) == chars_before + 1
