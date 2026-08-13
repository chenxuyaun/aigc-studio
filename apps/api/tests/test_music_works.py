"""音乐作品 API：定稿保存/列表/删除 + 圆桌限流。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
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

    r2 = await client.get("/api/v1/generations/music/works", headers=_headers(user_token))
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
    assert any("空洞赞颂" in w for w in warnings), warnings


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


async def test_backfill_work_material_saves_and_dedups(client) -> None:
    """好作品回填知识库（真实库验证）：首次保存；同标题二次调用被查重拦截；防刷限流。"""
    from unittest.mock import AsyncMock, patch

    import app.api.v1.generations.music as music_mod
    from app.models.text_document import TextDocument
    from sqlalchemy import func, select

    from tests.conftest import TestingSessionLocal

    lyrics = "【主歌1】老闸口吱呀响，红薯粥的热气冲进菜场，孩子把纸条贴在砖墙。" * 12

    async with TestingSessionLocal() as db:
        with (
            patch("app.core.database.AsyncSessionLocal", return_value=db),
            # 防刷窗口置负：两次调用都过防刷，第二次由「查重」拦截（测试意图）
            patch("app.api.v1.generations.music._BACKFILL_MIN_INTERVAL", -1),
            patch(
                "app.services.knowledge_materials.summarize_for_creation",
                new=AsyncMock(return_value="【AI 精华解读】…"),
            ),
        ):
            await music_mod._backfill_work_material(
                user_id="u1", work_title="灯火巷口", theme="歌颂劳动者",
                lyrics=lyrics, chords="C G", arrangement="民谣",
            )
            await music_mod._backfill_work_material(
                user_id="u1", work_title="灯火巷口", theme="歌颂劳动者",
                lyrics=lyrics, chords="C G", arrangement="民谣",
            )

    async with TestingSessionLocal() as db2:
        count = (
            await db2.execute(
                select(func.count(TextDocument.id)).where(
                    TextDocument.user_id == "u1",
                    TextDocument.title == "创作范例·灯火巷口",
                )
            )
        ).scalar_one()
    assert count == 1, "同标题第二次调用应被查重拦截（只存一份）"


async def test_auto_tags_llm_extracts(client) -> None:
    """LLM 从歌词提取风格/主题标签；逗号分隔。"""

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

    from app.api.v1.generations.music import _extract_fix_list

    rounds = [{"speaker": "词人", "content": "方案：用灯光意象"}]
    with patch("app.services.provider_resolver.resolve_text_provider") as m_r:
        assert await _extract_fix_list(None, rounds) == ""
    m_r.assert_not_awaited()


def test_validate_lyrics_flags_literary_style():
    """定稿自检：作文腔/鸡汤词触发自动重写（门不再放行散文诗）。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    literary = """【主歌1】铁皮温热，还留着白天焊枪刚撤走的呼吸
整个空车间突然很轻，静得能听见夜班在褪尽
而十二年的焊点，在更衣柜里悄悄排成行
【副歌】焊条当蜡烛火苗轻颤
可它自己学会了灿烂
【主歌2】呵气在铁皮上结霜，想象它开出深夜的厂房
【桥段】铁皮学会用光斑抚摸未凉的焊点，像淘尽了十二年沙
【副歌】铁皮在黑夜不发一言
可它自己找到了光芒"""
    checks = _validate_lyrics(literary)
    assert any("作文腔" in c for c in checks), "作文腔应被拦截"
    assert any("空洞赞颂" in c for c in checks), "鸡汤词应被拦截"
    assert _severe_checks(checks), "应触发自动重写"

    plain = """【主歌1】老周提前四十分钟到岗，用废料拼车模藏在更衣柜
工友笑他傻，他擦掉面罩上的焊渣说：等拼完车门，我就去报成人高考
【副歌】等拼完车门，我就去报成人高考
等拼完车门，我就去报成人高考
【主歌2】车间熄灯后他还在敲，焊条烫穿了裤兜
师傅骂他两句，又帮他补了一针
【桥段】准考证复印件贴在车模挡风玻璃上，塑封膜起泡了
【副歌】等拼完车门，我就去报成人高考
等拼完车门，我就去报成人高考"""
    checks2 = _validate_lyrics(plain)
    assert not any("作文腔" in c for c in checks2), "口语化歌词不应误报"
    assert not any("空洞赞颂" in c for c in checks2), "口语化歌词不应误报"


def test_validate_lyrics_flags_missing_punchline():
    """点睛检测：全程白描无人物声音 → 触发自动重写；有心口之言不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    plain = """【主歌1】他拧小火，监控屏绿光来回扫
赊账单背面的字像在动
记账笔断水，他哈口气，划成一道痕
【副歌】天亮之前他把昨夜抄了三遍
一遍比一遍轻
轻到硬币落在收银台上
人没听见就走了
【主歌2】油渍洇开第三行，他没擦只是看着
【桥段】分不清哪张是诗，哪张是别人欠的帐
【副歌】天亮之前他把昨夜抄了三遍
一遍比一遍轻"""
    checks = _validate_lyrics(plain)
    assert any("点睛" in c for c in checks), "全程白描应被拦截"
    assert _severe_checks(checks), "应触发自动重写"

    with_punch = plain.replace("划成一道痕", "划成一道痕，他对自己说：别怕")
    checks2 = _validate_lyrics(with_punch)
    assert not any("点睛" in c for c in checks2), "有心口之言不应误报"


def test_validate_lyrics_flags_antithetical_hook():
    """钩子事件化：副歌首行若是道理对仗格言 → 拦截；具体事件句不误报。"""
    from app.api.v1.generations.music import _is_antithetical_hook, _severe_checks, _validate_lyrics

    # 对仗格言应命中
    assert _is_antithetical_hook("车铃响三声，夜路短一截") is True
    assert _is_antithetical_hook("他走他的路，我补我的乐") is True
    # 具体事件应不命中
    assert _is_antithetical_hook("栽进排水沟") is False
    assert _is_antithetical_hook("我那年下夜班，铃是个哑巴") is False

    # 完整歌词：对仗副歌触发重写
    lyrics = """【主歌1】棉纺厂后门，周建国把内胎按进水盆
【副歌】车铃响三声，夜路短一截，
车铃响三声，腰也能直一些。
【主歌2】玲姐推着嘎吱的后轮
【桥段】我那年下夜班，铃是个哑巴，栽进排水沟
【副歌】车铃响三声，夜路短一截，
车铃响三声，腰也能直一些。"""
    checks = _validate_lyrics(lyrics)
    assert any("格言" in c for c in checks), "对仗格言副歌应被拦截"
    assert _severe_checks(checks), "应触发自动重写"

    # 事件式副歌不误报
    lyrics2 = """【主歌1】老周把内胎按进水盆
【副歌】我那年下夜班，铃是个哑巴，栽进排水沟
车铃擦得发亮，他按三下才放人走
【主歌2】红黄蓝胶带缠三道
【桥段】不是为你好，是我不信邪
【副歌】我那年下夜班，铃是个哑巴，栽进排水沟
车铃擦得发亮，他按三下才放人走"""
    checks2 = _validate_lyrics(lyrics2)
    assert not any("格言" in c for c in checks2), "事件式副歌不应误报"
