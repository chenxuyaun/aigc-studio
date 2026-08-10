"""音乐作品 API：定稿保存/列表/删除 + 圆桌限流。"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.models.music_work import MusicWork

from tests.conftest import TestingSessionLocal


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_save_and_list_work(client, user_token) -> None:
    """保存定稿 → 列表可见。"""
    r = await client.post(
        "/api/v1/generations/music/works",
        headers=_headers(user_token),
        json={
            "title": "归灯",
            "theme": "深夜归家",
            "style": "民谣",
            "lyrics": "【主歌1】雨幕敲卡槽…\n【副歌】加班的夜…",
            "arrangement": "D 小调 78 BPM",
            "style_en": "folk",
            "rounds": [{"speaker": "作词人", "content": "用具体意象"}],
            "source": "roundtable",
        },
    )
    assert r.status_code == 200
    assert r.json()["title"] == "归灯"

    r2 = await client.get(
        "/api/v1/generations/music/works", headers=_headers(user_token)
    )
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) >= 1
    mine = next((w for w in items if w["title"] == "归灯"), None)
    assert mine is not None
    assert "【主歌1】" in mine["lyrics"]
    assert mine["rounds"][0]["speaker"] == "作词人"


@pytest.mark.asyncio
async def test_delete_work(client, user_token) -> None:
    """删除作品。"""
    r = await client.post(
        "/api/v1/generations/music/works",
        headers=_headers(user_token),
        json={"title": "待删", "lyrics": "x"},
    )
    work_id = r.json()["id"]
    r2 = await client.delete(
        f"/api/v1/generations/music/works/{work_id}",
        headers=_headers(user_token),
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    async with TestingSessionLocal() as db:
        assert await db.get(MusicWork, work_id) is None


def test_rate_limit_roundtable_window() -> None:
    """圆桌限流：每用户每分钟 3 场，超限拒绝，窗口过期恢复。"""
    from app.api.v1.generations.music import (
        _ROUNDTABLE_WINDOW,
        _rate_limit_roundtable,
        _roundtable_hits,
    )

    _roundtable_hits.clear()
    uid = "rate-test-user"
    assert _rate_limit_roundtable(uid) is True
    assert _rate_limit_roundtable(uid) is True
    assert _rate_limit_roundtable(uid) is True
    assert _rate_limit_roundtable(uid) is False  # 第 4 次超限
    # 模拟窗口过期
    import time as _time

    _roundtable_hits[uid] = [_time.monotonic() - _ROUNDTABLE_WINDOW - 1]
    assert _rate_limit_roundtable(uid) is True  # 恢复
    _roundtable_hits.clear()


@pytest.mark.asyncio
async def test_works_requires_auth(client) -> None:
    """未登录 → 401。"""
    r = await client.get("/api/v1/generations/music/works")
    assert r.status_code == 401


def test_repair_lyrics_merges_duplicate_tags() -> None:
    """程序化修复：重复段落标签合并（主歌/桥段各 1 段，副歌最多 2 遍）。"""
    from app.api.v1.generations.music import _repair_lyrics

    lyrics = (
        "【主歌1】第一句\n"
        "【主歌1】第二句\n"
        "【副歌】副歌A1\n"
        "【副歌】副歌A2\n"
        "【主歌2】第三句\n"
        "【桥段】桥段句\n"
        "【桥段】桥段句2\n"
        "【副歌】副歌B1\n"
        "【副歌】副歌B2\n"
        "【副歌】副歌B3\n"
    )
    fixed = _repair_lyrics(lyrics)
    assert fixed.count("【主歌1】") == 1
    assert fixed.count("【主歌2】") == 1
    assert fixed.count("【桥段】") == 1
    assert fixed.count("【副歌】") == 2
    # 合并后的内容行保留
    assert "第二句" in fixed
    assert "副歌B3" in fixed
    # 顺序：副歌B3 并入第二次副歌之后
    assert fixed.index("【副歌】") < fixed.index("副歌B3")


def test_validate_lyrics_flags_hollow_praise_words() -> None:
    """空洞赞颂词检测：对着模糊对象喊口号（步伐/鼓点/星火/路标）应被警告。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = (
        "【主歌1】雨后巷口，旧自行车的轮胎在泥泞里咯吱。\n"
        "【副歌】我们跟着你的步伐向前走，这条街的节拍是时代的鼓点，汗水凝成星火，映出明天的路标。\n"
        "【副歌】我们跟着你的步伐向前走，这条街的节拍是时代的鼓点，汗水凝成星火，映出明天的路标。\n"
        "【主歌2】少年抬头，你俯身递出热油条。\n"
        "【桥段】你的笑声像雨后锈铁。\n"
    )
    warnings = _validate_lyrics(lyrics)
    assert any("空洞赞颂词" in w for w in warnings), warnings


def test_validate_lyrics_no_false_positive_on_concrete_lyrics() -> None:
    """具体落地的好词（灯塔/力量 等词少出现且有实物支撑）不应误报空洞赞颂。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = (
        "【主歌1】老闸口吱呀响，红薯粥的热气冲进菜场。\n"
        "【副歌】热饭盒里有咱的砰砰笑，这份暖像泥土的回声。\n"
        "【副歌】热饭盒里有咱的砰砰笑，这份暖像泥土的回声。\n"
        "【主歌2】她把纸条贴在砖墙，孩子们朗读红色家书。\n"
        "【桥段】那份平凡的热度，点亮了巷口的星火。\n"
    )
    warnings = _validate_lyrics(lyrics)
    assert not any("空洞赞颂词" in w for w in warnings), warnings


def test_severe_checks_detects_rewritable_problems() -> None:
    """严重自检警告（空洞赞颂/缺段落/押韵偷懒）应判定为需要自动重写。"""
    from app.api.v1.generations.music import _severe_checks

    assert _severe_checks(["空洞赞颂词过密（步伐鼓点星火路标）"])
    assert _severe_checks(["缺少【桥段】段落"])
    assert _severe_checks(["副歌句尾反复用「光」字（押韵偷懒）"])
    # 轻提示（字数/副歌次数）不触发重写
    assert not _severe_checks(["歌词偏短（120字，建议 260-450）"])
    assert not _severe_checks([])


async def test_backfill_work_material_saves_and_dedups() -> None:
    """好作品回填知识库：首次保存，同标题去重，防刷限流。"""
    from unittest.mock import AsyncMock, patch

    from app.api.v1.generations.music import (
        _backfill_lock,
        _backfill_work_material,
    )

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = None  # 同步方法，用 MagicMock
    fake_session.execute = AsyncMock(return_value=fake_result)  # execute 是 async
    fake_session.commit = AsyncMock()

    lyrics = "【主歌1】老闸口吱呀响，红薯粥的热气冲进菜场，孩子把纸条贴在砖墙。" * 10  # 足够长

    with (
        patch("app.api.v1.generations.music._backfill_lock", {}),
        patch(
            "app.core.database.AsyncSessionLocal",
            return_value=fake_session,
        ),
        patch(
            "app.services.knowledge_materials.summarize_for_creation",
            new=AsyncMock(return_value="【AI 精华解读】…"),
        ),
    ):
        await _backfill_work_material(
            user_id="u1", work_title="灯火巷口", theme="歌颂劳动者",
            lyrics=lyrics, chords="C G", arrangement="民谣",
        )
        await _backfill_work_material(
            user_id="u1", work_title="灯火巷口", theme="歌颂劳动者",
            lyrics=lyrics, chords="C G", arrangement="民谣",
        )
    assert fake_session.add.call_count == 1, "同标题第二次调用应去重"
    assert fake_session.commit.await_count == 1
    # 防刷：不同标题但 10 分钟内也不该再写（进程内窗口）
    with (
        patch("app.api.v1.generations.music._backfill_lock", {"u1": 10**9}),
        patch("app.core.database.AsyncSessionLocal") as m_session,
    ):
        await _backfill_work_material(
            user_id="u1", work_title="另一首", theme="x",
            lyrics=lyrics, chords="", arrangement="",
        )
    m_session.assert_not_called()


# ---------- 自动打标签 ----------


async def test_auto_tags_llm_extracts(client) -> None:
    """LLM 从歌词提取风格/主题标签；逗号分隔。"""
    from unittest.mock import AsyncMock, patch

    from app.services.music_works import _auto_tags

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": '{"tags": "民谣,劳动者,思乡"}'}
    )()
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        tags = await _auto_tags(None, "码头夜", "码头工人的一天", "民谣", "歌词内容")
    assert tags == "民谣,劳动者,思乡"


async def test_auto_tags_fallback_to_style(client) -> None:
    """LLM 失败降级为风格标签（保存不阻塞）。"""
    from unittest.mock import AsyncMock, patch

    from app.services.music_works import _auto_tags

    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.side_effect = RuntimeError("llm down")
    fake_resolver.model = "mock"
    with patch("app.services.provider_resolver.resolve_text_provider", return_value=fake_resolver):
        assert await _auto_tags(None, "歌", "", "民谣", "歌词") == "民谣"


# ---------- 歌词唱感检查 ----------


def test_validate_lyrics_flags_uneven_line_length() -> None:
    """唱感不齐：段内某句明显长于均值应警告（长句压垮旋律）。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = (
        "【主歌1】清晨四点，他拧开锈掉的铁门。\n"
        "【主歌1】灯下的影子拉得很长很长很长，比整条巷子还要长出几个身位。\n"
        "【主歌1】风把旧报纸吹到台阶上。\n"
        "【副歌】灯火巷口不灭，热饭盒里有咱的砰砰笑，这份温暖像泥土的回声，传到每个人的眉间，让汗水化作歌声飘向远方。\n"
        "【副歌】灯火巷口不灭，热饭盒里有咱的砰砰笑，这份温暖像泥土的回声。\n"
        "【主歌2】他把纸条贴在砖墙。\n"
        "【主歌2】孩子踮脚够不到窗台。\n"
        "【主歌2】纸条在风里翻了个身。\n"
        "【桥段】红薯粥的甜味，浸进每一块砖瓦。\n"
        "【桥段】这份平凡的热度，点亮了巷口。\n"
        "【桥段】星火落在窗台上。\n"
    )
    warnings = _validate_lyrics(lyrics)
    assert any("唱感不齐" in w for w in warnings), warnings


def test_validate_lyrics_balanced_lines_no_warning() -> None:
    """句长均衡的好词不应误报唱感不齐。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = (
        "【主歌1】老闸口吱呀响，红薯粥的热气冲进菜场。\n"
        "【副歌】热饭盒里有咱的砰砰笑，这份暖像泥土的回声。\n"
        "【副歌】热饭盒里有咱的砰砰笑，这份暖像泥土的回声。\n"
        "【主歌2】她把纸条贴在砖墙，孩子们朗读家书。\n"
        "【桥段】那份平凡的热度，点亮了巷口的星火。\n"
    )
    warnings = _validate_lyrics(lyrics)
    assert not any("唱感不齐" in w for w in warnings), warnings


# ---------- 批评→替代方案清单 ----------


async def test_extract_fix_list_returns_fixes(client) -> None:
    """讨论中含批评+替代：结构化提取为必改清单。"""
    from unittest.mock import AsyncMock, patch

    from app.api.v1.generations.music import _extract_fix_list

    rounds = [
        {"speaker": "词人", "content": "方案：用灯光意象"},
        {"speaker": "毒评", "content": "批评：灯光太俗。替代：换老闸口吱呀声"},
    ]
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": '{"fixes": ["- 批评：「灯光」→ 替代：「老闸口吱呀声」"]}'}
    )()
    fake_resolver.model = "mock"
    with patch("app.api.v1.generations.music.resolve_text_provider", return_value=fake_resolver):
        out = await _extract_fix_list(None, rounds)
    assert "老闸口吱呀声" in out


async def test_extract_fix_list_empty_without_criticism(client) -> None:
    """讨论无批评：直接返回空（不调用 LLM）。"""
    from unittest.mock import AsyncMock, patch

    from app.api.v1.generations.music import _extract_fix_list

    rounds = [{"speaker": "词人", "content": "方案：用灯光意象"}]
    with patch("app.services.provider_resolver.resolve_text_provider") as m_r:
        assert await _extract_fix_list(None, rounds) == ""
    m_r.assert_not_awaited()
