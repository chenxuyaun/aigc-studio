"""Mission 任务总控：拆解 → 执行 → 汇总。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from app.services import mission_service


@pytest.mark.asyncio
async def test_plan_mission_parses_plan(client):
    """LLM 拆解目标 → 计划（≤4 步，kind 白名单过滤）。"""
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R",
        (),
        {
            "content": json.dumps(
                {
                    "plan": [
                        {"kind": "music", "prompt": "矿工的清晨", "title": "写歌"},
                        {"kind": "image", "prompt": "矿井逆光", "title": "配图"},
                        {"kind": "hack", "prompt": "非法步骤", "title": "x"},
                    ]
                }
            )
        },
    )()
    fake_resolver.model = "mock"
    with (
        patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver),
        patch("app.services.mission_service._recent_lessons", new=AsyncMock(return_value=[])),
        patch("app.services.mission_service._available_agents", new=AsyncMock(return_value=[])),
        patch("app.services.profile_service.build_profile_text", new=AsyncMock(return_value="")),
    ):
        plan = await mission_service.plan_mission(None, "u1", "写一首矿工的歌并配图")
    assert [s["kind"] for s in plan] == ["music", "image"], "非法 kind 应被过滤"


@pytest.mark.asyncio
async def test_execute_step_search_failure(client):
    """search 步骤：检索失败返回 ok=False 且不抛异常。"""
    with patch("app.services.web_search.search_web", new=AsyncMock(return_value=[])):
        out = await mission_service.execute_step(None, "u1", {"kind": "search", "prompt": "x"})
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_execute_step_unknown_kind(client):
    out = await mission_service.execute_step(None, "u1", {"kind": "unknown", "prompt": "x"})
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_run_mission_falls_back_to_text(client):
    """拆解失败 → 降级为单步文本生成（不抛异常）。"""
    with (
        patch("app.services.mission_service.plan_mission", new=AsyncMock(return_value=[])),
        patch(
            "app.services.mission_service._execute_text",
            new=AsyncMock(return_value={"summary": "生成结果", "ok": True}),
        ),
        patch("app.services.mission_service._save_run", new=AsyncMock(return_value="run-1")),
    ):
        result = await mission_service.run_mission(None, "u1", "写一段欢迎词")
    assert len(result["results"]) == 1
    assert result["summary"].startswith("共 1 步")


@pytest.mark.asyncio
async def test_execute_agent_runs_and_leaves_state(client):
    """Agent 执行器：Identity 加载 → 生成 → State 留痕 + use_count 增长。"""
    from app.models.agent import Agent

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        session.add(
            Agent(
                id="agent-rt-1",
                name="资料整理员",
                author_id="u1",
                description="把资料整理成清单",
                system_prompt="你是资料整理员，输出结构化清单。",
                agent_type="generic",
                use_count=0,
            )
        )
        await session.commit()

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": "1. 调研口述史 2. 数字化记录"}
    )()
    fake_resolver.model = "mock"
    async with TestingSessionLocal() as session:
        with patch(
            "app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver
        ):
            out = await mission_service._execute_agent(session, "u1", "整理行动清单", "资料整理员")
    assert out["ok"] is True
    assert "资料整理员" in out["summary"]
    assert out["agent"] == "资料整理员", "执行结果应透传 Agent 名（前端徽章）"

    from app.models.agent_run import AgentRun
    from sqlalchemy import select

    async with TestingSessionLocal() as session:
        runs = (await session.execute(select(AgentRun))).scalars().all()
        assert len(runs) == 1, "Agent 执行应留痕"
        assert runs[0].status == "done"
        agent = (await session.execute(select(Agent).where(Agent.id == "agent-rt-1"))).scalar_one()
        assert agent.use_count == 1, "use_count 应增长"


@pytest.mark.asyncio
async def test_aggregate_preferences_and_injection(client):
    """成长档案：从创作记录聚合偏好，注入文本含【用户偏好】块。"""
    from app.services.profile_service import aggregate_preferences, build_profile_text

    from tests.conftest import TestingSessionLocal

    # 造数据：一首民谣作品 + 一条 mission run
    async with TestingSessionLocal() as session:
        from app.models.mission_run import MissionRun
        from app.models.music_work import MusicWork
        from app.models.user import User
        from sqlalchemy import select

        uid = (await session.execute(select(User.id).where(User.username == "admin"))).scalar_one()
        session.add(
            MusicWork(
                user_id=uid,
                title="试听",
                theme="故乡",
                style="民谣",
                tags="民谣,思乡",
                lyrics="词",
                source="roundtable",
            )
        )
        session.add(
            MissionRun(
                user_id=uid,
                goal="写歌",
                plan='[{"kind": "music", "title": "写歌"}]',
                results="[]",
                summary="ok",
            )
        )
        await session.commit()

    async with TestingSessionLocal() as session:
        from app.models.user import User as _User
        from sqlalchemy import select as _select

        _uid = (
            await session.execute(_select(_User.id).where(_User.username == "admin"))
        ).scalar_one()
        prefs = await aggregate_preferences(session, str(_uid))
        assert "民谣" in prefs["styles"] or "思乡" in prefs["themes"]
        text = await build_profile_text(session, str(_uid))
    assert "【用户偏好】" in text


@pytest.mark.asyncio
async def test_execute_story_and_asmr_kinds(client):
    """融合验证：story kind 生成正文；asmr kind 检索素材（无命中 ok=False）。"""
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": "老周推开戏园后门。锣鼓声歇了，他数了数怀里的烟。"}
    )()
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await mission_service._execute_story(None, "u1", "写戏园一幕")
    assert out["ok"] is True
    assert "老周" in out["summary"]

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        out2 = await mission_service._execute_asmr(session, "u1", "绝对不存在的主题xyz")
    assert out2["ok"] is False


@pytest.mark.asyncio
async def test_execute_character_and_memory_kinds(client):
    """角色/记忆引擎融合：角色卡回应；无记忆档案时 ok=False。"""
    from app.models.roleplay_character import RoleplayCharacter

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        session.add(
            RoleplayCharacter(
                asset_id="char-fuse-1",
                user_id="u1",
                name="老周",
                description="戏园守门人，沉默寡言",
                personality="念旧",
                scenario="",
                first_mes="",
                mes_example="",
                system_prompt="",
                post_history_instructions="",
                creator_notes="",
                tags="[]",
            )
        )
        await session.commit()

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": "我守这门四十年了，风雨都见过。"}
    )()
    fake_resolver.model = "mock"
    async with TestingSessionLocal() as session:
        with patch(
            "app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver
        ):
            out = await mission_service._execute_character(session, "u1", "聊聊守门的日子", "老周")
        assert out["ok"] is True
        assert "老周" in out["summary"]
        # 无记忆档案 → ok=False（不抛异常）
        out2 = await mission_service._execute_memory(session, "u1", "查记忆", "老周")
    assert out2["ok"] is False


@pytest.mark.asyncio
async def test_execute_code_kind_generates_files(client):
    """代码引擎：LLM 产出文件集（path/content），ok=True。"""
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R",
        (),
        {
            "content": json.dumps(
                {
                    "files": [
                        {
                            "path": "app.py",
                            "content": "from flask import Flask\napp = Flask(__name__)\n",
                        },
                        {"path": "README.md", "content": "# 待办应用"},
                    ],
                    "note": "python app.py",
                }
            )
        },
    )()
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        out = await mission_service._execute_code(None, "u1", "做一个 Flask 待办应用")
    assert out["ok"] is True
    assert len(out["code"]) == 2
    assert out["code"][0]["path"] == "app.py"
    assert "python app.py" in out["summary"]


@pytest.mark.asyncio
async def test_execute_music_saves_work_and_backfills(client):
    """生长闭环：Mission 音乐步骤的产出 → 作品库落库 + 后台回填知识库。"""
    import asyncio as _asyncio

    from app.models.music_work import MusicWork
    from sqlalchemy import select as _select

    from tests.conftest import TestingSessionLocal

    fake_data = {
        "title": "夏光影",
        "lyrics": "让微风偷走我的烦恼\n清晨的露珠在旧木门前踢踏\n" * 20,  # ≥200 字满足回填条件
        "chords": "C G Am F",
        "arrangement": "木吉他 + 口琴",
        "style": "民谣",
    }
    backfill_mock = AsyncMock()
    with (
        patch(
            "app.api.v1.generations.music.compose_song",
            new=AsyncMock(return_value=dict(fake_data)),
        ),
        patch("app.api.v1.generations.music._backfill_work_material", new=backfill_mock),
        patch("app.services.music_works._auto_tags", new=AsyncMock(return_value="民谣,夏日")),
    ):
        async with TestingSessionLocal() as session:
            out = await mission_service.execute_step(
                session,
                "u1",
                {"kind": "music", "prompt": "写一首关于夏天的歌"},
                goal="写一首关于夏天的民谣",
            )
            # 等后台回填任务跑完（回填是 create_task 异步执行）
            for _ in range(40):
                if backfill_mock.await_count:
                    break
                await _asyncio.sleep(0.05)
            works = await session.execute(_select(MusicWork).where(MusicWork.title == "夏光影"))
            saved = works.scalar_one_or_none()
            assert saved is not None, "Mission 产出的歌应存入作品库"
            assert saved.theme == "写一首关于夏天的民谣", "作品主题应继承用户原始目标"
    assert out["ok"] is True
    assert backfill_mock.await_count >= 1, "应触发知识库回填"


@pytest.mark.asyncio
async def test_execute_agent_auto_spawns_when_missing(client):
    """编排水位：Orchestrator 指派不存在的角色 → 现场创建专属 Agent 再执行。"""
    from app.models.agent import Agent as AgentModel
    from sqlalchemy import select as _select

    from tests.conftest import TestingSessionLocal

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": "灯下修鞋匠：三十年顶针磨亮，退休那天把工具箱传给徒弟。"}
    )()
    fake_resolver.model = "mock"
    async with TestingSessionLocal() as session:
        with patch(
            "app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver
        ):
            out = await mission_service._execute_agent(
                session, "u1", "写民谣人物小传", "民谣词人"
            )
    assert out["ok"] is True
    assert out["agent"] == "民谣词人", "执行结果应带现场创建的 Agent 名"
    async with TestingSessionLocal() as session:
        agent = (
            await session.execute(
                _select(AgentModel).where(AgentModel.name == "民谣词人")
            )
        ).scalars().first()
        assert agent is not None, "应现场创建专属 Agent"
        assert agent.agent_type == "mission"
        assert "民谣词人" in agent.system_prompt
    # 再次执行同一角色：复用不重复创建
    async with TestingSessionLocal() as session:
        with patch(
            "app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver
        ):
            out2 = await mission_service._execute_agent(
                session, "u1", "再写一篇", "民谣词人"
            )
    assert out2["ok"] is True
    async with TestingSessionLocal() as session:
        from sqlalchemy import func as _func

        n = (
            await session.execute(
                _select(_func.count()).select_from(AgentModel).where(
                    AgentModel.name == "民谣词人"
                )
            )
        ).scalar_one()
        assert n == 1, "同名角色应复用，不重复创建"


@pytest.mark.asyncio
async def test_execute_music_injects_agent_role(client):
    """角色编排：music 步骤带 agent 时，角色设定注入创作提示且现场创建 Agent。"""
    from app.models.agent import Agent as AgentModel
    from sqlalchemy import select as _select

    from tests.conftest import TestingSessionLocal

    captured: dict[str, str] = {}

    async def _fake_compose(req, _db, _uid):
        captured["theme"] = req.theme
        return {
            "title": "车站",
            "lyrics": "绿皮火车在深夜进站\n" * 12,
            "chords": "C G",
            "arrangement": "口琴",
            "style": "民谣",
        }

    with (
        patch("app.api.v1.generations.music.compose_song", new=_fake_compose),
        patch("app.api.v1.generations.music._backfill_work_material", new=AsyncMock()),
        patch("app.services.music_works._auto_tags", new=AsyncMock(return_value="民谣")),
    ):
        async with TestingSessionLocal() as session:
            out = await mission_service._execute_music(
                session, "u1", "写老火车站的歌", theme_goal="g", agent_name="民谣词人"
            )
    assert out["ok"] is True
    assert "民谣词人" in captured["theme"], "角色设定应注入创作提示"
    async with TestingSessionLocal() as session:
        agent = (
            await session.execute(
                _select(AgentModel).where(AgentModel.name == "民谣词人")
            )
        ).scalars().first()
        assert agent is not None, "应现场创建角色 Agent"
        assert agent.agent_type == "mission"


@pytest.mark.asyncio
async def test_continue_mission_chains_to_parent(client):
    """多轮对话：continue 组装延续目标（含上次产出+追问），parent_run_id 关联成链。"""
    from app.models.mission_run import MissionRun
    from sqlalchemy import select as _select

    from tests.conftest import TestingSessionLocal

    async with TestingSessionLocal() as session:
        session.add(
            MissionRun(
                id="run-parent-1",
                user_id="u1",
                goal="写一首关于夏天的歌",
                plan="[]",
                results='[{"step":1,"kind":"music","summary":"《夏光影》歌词","ok":true}]',
                summary="ok",
            )
        )
        await session.commit()

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type("R", (), {"content": "好的"})()
    fake_resolver.model = "mock"
    with (
        patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver),
        patch("app.services.mission_service.plan_mission", new=AsyncMock(return_value=[])),
    ):
        async with TestingSessionLocal() as session:
            out = await mission_service.continue_mission(
                session, "u1", "run-parent-1", "副歌再温暖一点"
            )
    assert out is not None
    assert out["run_id"]
    assert "副歌再温暖一点" in out["goal"], "追问应进入新一轮目标"
    assert "上次目标" in out["goal"]
    assert "上次产出" in out["goal"]
    async with TestingSessionLocal() as session:
        child = (
            await session.execute(
                _select(MissionRun).where(MissionRun.id == out["run_id"])
            )
        ).scalar_one()
        assert child.parent_run_id == "run-parent-1", "应关联父会话成链"
    # 不存在的会话 → None（调用方 404）
    async with TestingSessionLocal() as session:
        none_out = await mission_service.continue_mission(session, "u1", "no-such", "x")
    assert none_out is None


@pytest.mark.asyncio
async def test_execute_music_truncates_long_theme(client):
    """多轮对话长目标：theme 超 500 字时截断，不触发 validation error。"""
    captured: dict[str, str] = {}

    async def _fake_compose(req, _db, _uid):
        captured["theme"] = req.theme
        return {
            "title": "x",
            "lyrics": "词\n" * 120,
            "chords": "C",
            "arrangement": "",
            "style": "民谣",
        }

    long_prompt = "写一首关于山间晨雾的民谣" + "，加上阳光意象和露珠细节" * 40
    with (
        patch("app.api.v1.generations.music.compose_song", new=_fake_compose),
        patch("app.api.v1.generations.music._backfill_work_material", new=AsyncMock()),
        patch("app.services.music_works._auto_tags", new=AsyncMock(return_value="民谣")),
    ):
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            out = await mission_service._execute_music(
                session, "u1", long_prompt, theme_goal="g"
            )
    assert out["ok"] is True, "超长 theme 应被截断而非报错"
    assert len(captured["theme"]) <= 500


@pytest.mark.asyncio
async def test_execute_plan_cleans_and_runs(client):
    """人工干预：提交的 plan 经白名单过滤（非法 kind 丢弃）+ 兜底降级。"""
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type("R", (), {"content": "好的"})()
    fake_resolver.model = "mock"
    plan = [
        {"kind": "text", "prompt": "写一段", "title": "a"},
        {"kind": "hack", "prompt": "evil", "title": "b"},
    ]
    with patch(
        "app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver
    ):
        from tests.conftest import TestingSessionLocal

        async with TestingSessionLocal() as session:
            out = await mission_service.execute_plan(session, "u1", "目标", plan)
    assert out["summary"].startswith("共 1 步"), "非法 kind 应被过滤"
    assert out["results"][0]["ok"] is True
    assert out["run_id"]
