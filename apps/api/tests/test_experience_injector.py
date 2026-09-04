"""Experience Injector 测试：创作路由（story/music/roundtable）注入用户真实经历素材。

覆盖：
- build_experience_prompt：只取 event/emotion 类记忆；无素材空串；长度截断
- music compose_song：带 user_id 时 prompt 含「真实经历素材」
- roundtable stream：所有发言人轮次与定稿轮 prompt 含素材
- story _build_chapter_prompt：system prompt 含素材
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.growth import MemoryEntry


async def _seed_memory(user_id: str, kind: str, content: str) -> None:
    # 函数内 import：conftest 会在 fixture 阶段替换 AsyncSessionLocal 指向测试内存库
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(MemoryEntry(user_id=user_id, kind=kind, content=content))
        await db.commit()


async def _seed_memories(user_id: str) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        db.add(MemoryEntry(user_id=user_id, kind="preference", content="喜欢短句"))
        db.add(MemoryEntry(user_id=user_id, kind="fact", content="长住江边"))
        db.add(MemoryEntry(user_id=user_id, kind="event", content="在桥洞下摆过三年早点摊，最怕下暴雨"))
        db.add(MemoryEntry(user_id=user_id, kind="emotion", content="最近常想起外婆熬的粥"))
        await db.commit()


# ===== build_experience_prompt（纯查询）=====


@pytest.mark.asyncio
async def test_build_empty_without_event_memories() -> None:
    """只有偏好/事实类记忆（不构成经历）→ 空串（创作不塞无关素材）。"""
    from app.applications.experience_injector import build_experience_prompt

    await _seed_memory("u-nope", "preference", "用户喜欢短句")
    await _seed_memory("u-nope", "fact", "用户住苏州")
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        out = await build_experience_prompt(db, "u-nope")
    assert out == ""


@pytest.mark.asyncio
async def test_build_returns_event_and_emotion_with_labels() -> None:
    from app.applications.experience_injector import build_experience_prompt

    await _seed_memories("u-exp1")
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        out = await build_experience_prompt(db, "u-exp1")
    assert out.startswith("【你的真实经历素材")
    assert "桥洞" in out
    assert "- [事件]" in out
    assert "外婆" in out
    assert "短句" not in out


@pytest.mark.asyncio
async def test_build_respects_max_chars() -> None:
    from app.applications.experience_injector import build_experience_prompt

    long = "他总在收摊后数一遍零钱，铜板的声音很轻，" * 30
    await _seed_memory("u-big", "event", long)
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        out = await build_experience_prompt(db, "u-big", max_chars=200)
    assert 0 < len(out) < 200 + 200  # 截断（一行可能突破阈值，但整体有界）


# ===== music：compose_song / roundtable_single =====

_CLEAN_LYRICS = (
    "【主歌1】天没亮，路灯下卖粥的掀开锅盖\n"
    "白汽扑上玻璃，糊了半扇窗\n"
    "他把米汤撇进桶，锅底刮三遍\n"
    "末班车过站台，灯晃了一下\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "他把粥温着，像温着一句话\n"
    "【主歌2】收摊时剩粥倒给流浪猫\n"
    "猫不来，粥凉在桶里没人喝\n"
    "早班车灯扫过，他背过身擦碗\n"
    "街对过那盏灯，昨晚还亮着\n"
    "【桥段】他说，明天还来，天总会亮的\n"
    "抹布搭在缸沿，像个人还在等\n"
    "那碗粥凉了又热，热了又凉\n"
    "他把粥温着，像温着一句话\n"
    "【副歌2】雾漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "她把粥温着，像温着一句话"
)


def _lyrics_result(lyrics: str):
    return type(
        "R",
        (),
        {"content": json.dumps({"title": "桥东粥铺", "style_zh": "市井", "lyrics": lyrics})},
    )()


@pytest.mark.asyncio
async def test_music_compose_injects_experience() -> None:
    """compose_song 带 user_id：上游收到的 prompt 含「真实经历素材」块。"""
    import app.core.runtime.music.engine as engine

    await _seed_memories("u-mus")
    res = AsyncMock()
    res.model = "mock"
    sent: list[str] = []
    real = _lyrics_result(_CLEAN_LYRICS)

    async def _fake_gen(prompt, model, **kw):
        sent.append(prompt)
        return real

    res.provider.generate = _fake_gen
    with patch.object(engine, "resolve_text_provider", return_value=res):
        from app.core.runtime.music.engine import compose_song

        req = SimpleNamespace(
            theme="粥铺", style="民谣", mood="温暖", language="中文", verse_count=2, model=""
        )
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            out = await compose_song(db, req, user_id="u-mus")
    assert out.get("error") is None
    joined = "\n".join(sent)
    assert "真实经历素材" in joined and "桥洞" in joined


@pytest.mark.asyncio
async def test_music_compose_without_user_no_injection() -> None:
    """无 user_id（匿名/任务非用户场景）→ prompt 不含素材（行为与旧版一致）。"""
    import app.core.runtime.music.engine as engine

    sent: list[str] = []
    res = AsyncMock()
    res.model = "mock"
    real = _lyrics_result(_CLEAN_LYRICS)

    async def _fake_gen(prompt, model, **kw):
        sent.append(prompt)
        return real

    res.provider.generate = _fake_gen
    with patch.object(engine, "resolve_text_provider", return_value=res):
        from app.core.runtime.music.engine import compose_song

        req = SimpleNamespace(
            theme="粥铺", style="民谣", mood="温暖", language="中文", verse_count=2, model=""
        )
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await compose_song(db, req)  # 无 user_id → 匿名/任务场景
    assert all("真实经历素材" not in p for p in sent)


# ===== roundtable：stream_roundtable =====


@pytest.mark.asyncio
async def test_roundtable_speaker_and_final_prompt_include_experience() -> None:
    """进入发言人轮次后 prompt 含素材（quick 模式：1 cast + 4 speak + 1 final）。"""
    from app.applications import roundtable_service as rt

    await _seed_memory("u1", "event", "在桥洞下卖过三年粥，最怕下暴雨")
    records: list[str] = []

    def _fake_gen(prompt, model, **kw):
        records.append(prompt)
        n = len(records)
        if n == 1:
            raise RuntimeError("cast 失败走兜底阵容")
        if n < 6:
            return SimpleNamespace(content="就按市井的细节写，别写空话。")
        body = (
            "老陈把半袋钱塞进麻袋口，像潮声在胸口滚。货摊支在桥洞下，铁皮炉子烧着隔夜煤。"
            "他把伞骨抵在膝盖上拗直，铁盒里的铜板磕得脆响。"
        )
        while len(body) < 340:
            body += "他把粥碗扣在缸沿上，等天亮前的最后一班车。"
        return SimpleNamespace(
            content=json.dumps({"title": "桥东粥铺", "content": body, "style": "市井"})
        )

    fake_res = SimpleNamespace(
        provider=SimpleNamespace(generate=_fake_gen), model="mock"
    )
    with patch.object(rt, "resolve_text_provider", return_value=fake_res):
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            events = [
                ev
                async for ev in rt.stream_roundtable(
                    db, user_id="u1", domain="copy", theme="桥东粥铺", quick=True
                )
            ]

    assert any("真实经历素材" in p for p in records)
    # 素材只进创作 prompt，不进 SSE 事件（不向用户泄露素材文本）
    assert "真实经历素材" not in json.dumps(events, ensure_ascii=False)
    assert "真实经历素材" in records[-1]  # 定稿轮 prompt 也有

# ===== story：_build_chapter_prompt =====


@pytest.mark.asyncio
async def test_story_system_prompt_includes_experience() -> None:
    """章节 prompt 组装（叙事模式）注入用户真实经历素材。"""
    from app.applications import story_forge

    await _seed_memory("u-story", "event", "小时候跟外公在桥洞底下躲过一场暴雨")

    project = SimpleNamespace(
        id="p1",
        title="夜航船",
        genre="公路",
        synopsis="一段关于告别与回家的旅程",
        settings="{}",
        character_asset_ids="[]",
    )
    chapter = SimpleNamespace(
        id="c1", chapter_no=1, title="出发", outline="主角启程", content="", word_count=0
    )
    cards = [("char1", {"name": "主角", "description": "沉默寡言的年轻船工"})]

    with (
        patch("app.applications.story_forge._story_history", new=AsyncMock(return_value=([], ""))),
        patch(
            "app.applications.roleplay._load_lore_entries", new=AsyncMock(return_value=[])
        ),
        patch(
            "app.applications.story_forge._bible_text",
            new=AsyncMock(return_value="主角性格设定：沉默寡言，认路不看路标"),
        ),
        patch("app.applications.story_forge._knowledge_refs", new=AsyncMock(return_value="")),
    ):
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            system_prompt, user_prompt, tb = await story_forge._build_chapter_prompt(
                db, "u-story", project, chapter, cards, ""
            )
    assert "真实经历素材" in system_prompt
    assert "暴雨" in system_prompt
