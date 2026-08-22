"""音乐作品 API：定稿保存/列表/删除 + 圆桌限流。"""

from __future__ import annotations

import json
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


def test_validate_lyrics_flags_self_intro_and_prose():
    """歌词性第一律：自报家门/散文长句触发自动重写；口语歌词不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    # 郑玉兰式人物卡：自报家门 + 一句塞 4 个并列信息 = 散文
    prose = """【主歌1】我是郑玉兰，夜班码头，风往东，船晚点四十分钟
我呵开结霜的玻璃，在第五页圈住最亮那颗星
【副歌】四点四十，我在第五页圈了颗星，标上最亮
你接班先看这一页，别问我在天上哪一处
【主歌2】天亮交班，老赵的保温杯里茶还烫
【桥段】二十三年，我把最亮的星都圈成同一颗
【副歌】四点四十，我在第五页圈了颗星，标上最亮
你接班先看这一页，别问我在天上哪一处"""
    checks = _validate_lyrics(prose)
    assert any("自报家门" in c for c in checks), "「我是XX」应被拦截"
    assert any("散文长句" in c for c in checks), "一句多并列信息应被拦截"
    assert _severe_checks(checks), "应触发自动重写"

    # 「我是真的」这类口语连用不误报；正常歌词不误报
    clean = """【主歌1】天没亮透，新华路的梧桐叶铺了一地
我把叶子码成圈，围住那棵撞歪的槐树
【副歌】我是真的，想再抱他一下
我是真的，话到嘴边又咽下
【主歌2】手抖得先靠扫帚站一会儿
【桥段】这树跟我一样，腿脚怕冷
【副歌】我是真的，想再抱他一下
我是真的，话到嘴边又咽下"""
    checks2 = _validate_lyrics(clean)
    assert not any("自报家门" in c for c in checks2), "「我是真的」不应误报自报家门"
    assert not any("散文长句" in c for c in checks2), "短行歌词不应误报散文长句"


def test_validate_lyrics_flags_warm_word_crutch():
    """暖词复用：情感落点用「热乎/焐软」收尾 → 拦截；具体暖意象不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    warm = """【主歌1】凌晨四点，柴油味往驾驶室挤
遮阳板上那张错字贴在透明胶里
【副歌】再跑二十公里，水壶嘴就响
这一路的热乎，够我跑到天亮
【主歌2】开水房白汽扑在搪瓷缸盖上
【桥段】过了乌鞘岭，那张字轻轻跳
【副歌】再跑二十公里，水壶嘴就响
这一路的热乎，够我跑到天亮"""
    checks = _validate_lyrics(warm)
    assert any("暖词复用" in c for c in checks), "「热乎」收尾应被拦截"
    assert _severe_checks(checks), "应触发自动重写"

    concrete = """【主歌1】凌晨四点，柴油味往驾驶室挤
遮阳板上那张错字贴在透明胶里
【副歌】再跑二十公里，水壶嘴就响
响在服务区凌晨，惊起檐下麻雀
【主歌2】开水房白汽扑在搪瓷缸盖上
【桥段】过了乌鞘岭，那张字轻轻跳
【副歌】再跑二十公里，水壶嘴就响
响在服务区凌晨，惊起檐下麻雀"""
    checks2 = _validate_lyrics(concrete)
    assert not any("暖词复用" in c for c in checks2), "具体暖意象不应误报"


def test_validate_lyrics_ascii_quote_counts_as_dialogue() -> None:
    """点睛检测：ASCII 双引号（模型常用）里的直接引语应算心口之言，不误报缺点睛。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = """【主歌1】井口晨雾轻，铁壶在咕噜咕噜冒着热气
他站在摊前，慢慢加糖搅拌
【副歌】晨粥暖，暖在心口
留杯给她的那杯
【主歌2】上个月她没来等，摊子冷清了些
他把豆浆盛满一碗，盖上盖子
【桥段】他低声呢喃，"姑娘，这碗留给你，喝完记得早点回来。"
【副歌】晨粥暖，暖在心口
留杯给她的那杯"""
    checks = _validate_lyrics(lyrics)
    assert not any("缺点睛" in c for c in checks), "ASCII 引号引语不应误报缺点睛"


def test_validate_lyrics_merged_chorus_no_false_rhyme_warning() -> None:
    """押韵检测：两遍副歌粘连在同一标签下（重复段句尾必相同）不应误报押韵偷懒。"""
    from app.api.v1.generations.music import _validate_lyrics

    lyrics = """【主歌1】凌晨四点，井口雾气轻
老李推开木棚的门
【副歌】老李把豆浆倒进杯
递到小梅手里边
她接过暖意在心
心跳跟着稳了
老李把豆浆倒进杯
递到小梅手里边
她接过暖意在心
从此夜路不冷
【主歌2】等了半小时，姑娘没来
老李又添了柴火
【桥段】她走近摊子，伸手接过
小梅，这杯能暖你一宿"""
    checks = _validate_lyrics(lyrics)
    assert not any("押韵偷懒" in c for c in checks), "粘连副歌重复不应误报押韵偷懒"


def test_repair_lyrics_normalizes_chorus2() -> None:
    """结构修复：模型用【副歌2】代替第二遍【副歌】→ 归一化为【副歌】。"""
    from app.api.v1.generations.music import _repair_lyrics

    lyrics = "【主歌1】A\n【副歌】B\n【主歌2】C\n【副歌2】B"
    fixed = _repair_lyrics(lyrics)
    assert fixed.count("【副歌】") == 2, "【副歌2】应归一化为【副歌】"
    assert "【副歌2】" not in fixed


def test_severe_checks_flags_missing_chorus_repeat() -> None:
    """严重性判断：副歌重复次数不足（结构不完整）应触发自动重写。"""
    from app.api.v1.generations.music import _severe_checks

    assert _severe_checks(["副歌重复次数不足（应至少 2 次）"])
    assert not _severe_checks(["歌词偏短（120字，建议 260-450）"])


def test_validate_lyrics_flags_overlong_line() -> None:
    """歌词感铁律：单句超 15 汉字（叙事诗式长句）→ 警告并触发自动重写；短句不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    # 桥段 17 字长句（整段都长，段内相对比较查不出 → 绝对阈值必拦）
    long_line = """【主歌1】凌晨四点她蹲在平江路河沿边看水
旧伞骨掰正，虎口勒出一道深弯
【副歌】她把旧伞一把把倒挂在河沿
不等人，只等这场雨小一点点
【主歌2】她把白胶布一圈圈地往伞柄上缠
借伞的人写：今晚要去哪个站呢
【桥段】雨落在我身上，才晓得女儿那天冷得多难
扫了十九年，这条河也还没把人还来
【副歌】她把旧伞一把把倒挂在河沿
不等人，只等这场雨小一点点"""
    checks = _validate_lyrics(long_line)
    assert any("长句" in c for c in checks), "17 字长句应被拦截"
    assert _severe_checks(checks), "长句应触发自动重写"

    # 全短句（≤12 字为主）不误报
    short = """【主歌1】凌晨四点，她蹲在河边
掰正伞骨，虎口勒出弯
【副歌】她把旧伞，一把把倒挂
不等人，只等雨小一点
【主歌2】白胶布缠上伞柄
借伞的人，写今晚去哪
【桥段】雨落身上，才知她那天多难
扫了十九年，河没把人还
【副歌】她把旧伞，一把把倒挂
不等人，只等雨小一点"""
    checks2 = _validate_lyrics(short)
    assert not any("长句" in c for c in checks2), "短句歌词不应误报长句"


def test_validate_lyrics_flags_thin_content() -> None:
    """信息密度铁律：全短句骨架化（<230 字、段句数不足）→ 拦截触发重写；饱满歌词不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    # 《雨里不卖》式单薄：每段 3-4 句、全 5-8 字短句、细节全丢
    thin = """【主歌1】
雨落渡口石阶旁
我坐最低那一档
头一朵白兰摘下来
搪瓷杯里接雨装
【副歌】
我留一朵花不卖
等它烂在雨里
末班船灯扫过河
我坐最低阶不起
【主歌2】
十年前梅雨天
找零钱抬头人不见
她爸到死怪我低头
搪瓷杯缺了十年
【桥段】
雨把石阶洗得发亮
十年就等一双鞋响
孩子回来不滑脚
【副歌】
我留一朵花不卖
等它烂在雨里
那年的跳板空着摆
我坐最低阶不起"""
    checks = _validate_lyrics(thin)
    assert any("单薄" in c for c in checks), "骨架化歌词应被拦截"
    assert _severe_checks(checks), "单薄应触发自动重写"

    # 饱满：主歌 6 句 + 细节 + 260+ 字
    rich = """【主歌1】梅雨天，雾漫到桥头
灰雨衣漾过，认不得是谁
竹竿上旧伞倒挂，我撑开一把
指腹湿一线，换根竹削骨
搪瓷缸沿磕掉一块，白瓷茬在雨里发亮
她那年就是走这条路，没打伞
【副歌】留个响，夜里像有人推门
留个响，夜里不像一个人
雨把跳板洗得发白，没人下来
留个响，等一双鞋踩过青石板
【主歌2】那年梅雨天，胥江翻船
你在船上，我在桥堍修伞
船工号子断在半截，我数到七
伞骨锈在门后，三年没动过
檐下滴水砸在搪瓷盆，一声一声
【桥段】修了三十年伞，没补自家三片瓦
留个响，雨声里等了十年
雨水顺着伞骨滴下，像没断的线
【副歌】留个响，夜里像有人推门
留个响，夜里不像一个人
雨把跳板洗得发白，没人下来
留个响，等一双鞋踩过青石板"""
    checks2 = _validate_lyrics(rich)
    assert not any("单薄" in c for c in checks2), "细节饱满的歌词不应误报单薄"


def test_validate_lyrics_flags_motivation_downgrade() -> None:
    """人物价值层级铁律：丧亲 + 守/等/留但无职业动作 = 动机降维 → 拦截；劳动细节充分不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    downgrade = """【主歌1】桥墩浇进她的名字
她走的那年，雨没停
我守着桥头看江水
江雾漫上来又散开
【副歌】我留着她的名字
等风把桥吹旧
【主歌2】图纸还压在箱底
她再没回来过一眼
桥灯亮着没人走
【桥段】通车那天我没去
【副歌】我留着她的名字
等风把桥吹旧"""
    checks = _validate_lyrics(downgrade)
    assert any("动机降维" in c for c in checks), "悲情覆盖价值应被拦截"
    assert _severe_checks(checks), "降维应触发自动重写"

    # 劳动细节充分：不误报降维
    labor = """【主歌1】凌晨四点，柴油味往驾驶室挤
遮阳板上那张错字贴在透明胶里
我咬开榨菜袋，秦岭隧道风灌进来
抬手把它按实，舍不得按太紧
【副歌】再跑二十公里，水壶嘴就响
响在服务区凌晨，像闺女喊我别着凉
写岔的远字在遮阳板上晃
这一路的热乎，够我跑到天亮
【主歌2】开水房白汽扑在搪瓷缸盖上
半张加油小票，背面写前头有雨慢些
方向盘三点钟方向，皮子磨得发亮
【桥段】过了乌鞘岭，那张字轻轻跳
二十三年了，她举着本子喊：爸
【副歌】再跑二十公里，水壶嘴就响
响在服务区凌晨，像闺女喊我别着凉"""
    checks2 = _validate_lyrics(labor)
    assert not any("动机降维" in c for c in checks2), "劳动细节充分不应误报降维"


def test_validate_lyrics_flags_symbol_overload() -> None:
    """反语义收敛铁律：第一联想符号 ≥6 个 = 符号过密 → 拦截触发重写。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    symbols = """【主歌1】烟雨漫过江南的桥
油纸伞撑在青瓦檐下
故人走过十年老街
风把灯吹晃
【副歌】雨落桥头，伞湿半边
【主歌2】江南的雨还在下
旧巷的灯还在亮
【桥段】雨和伞，桥和灯
【副歌】雨落桥头，伞湿半边"""
    checks = _validate_lyrics(symbols)
    assert any("符号过密" in c for c in checks), "第一联想符号堆砌应被拦截"
    assert _severe_checks(checks), "符号过密应触发自动重写"


def test_validate_lyrics_flags_no_rhyme_by_thirteen_zhe() -> None:
    """十三辙押韵校验：句尾字全不同辙（言前/人辰/怀来/发花互不押）→ 无韵拦截；同辙不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    # 句尾：山(言前) 门(人辰) 来(怀来) 下(发花) 停(中东) —— 5 字 5 辙全不同
    no_rhyme = """【主歌1】雨落渡口那座山
他靠在桥头看水门
风从江面吹过来
船桨横在石阶下
他数着日子等雨停
【副歌】他坐最低一档
等末班船过河
【主歌2】十年过去又一年
旧伞挂在竹竿边
【副歌】他坐最低一档
等末班船过河"""
    checks = _validate_lyrics(no_rhyme)
    assert any("无韵" in c for c in checks), "全不同辙句尾应判无韵"
    assert _severe_checks(checks), "无韵应触发自动重写"

    # 句尾同辙（言前：山/年/边/天）→ 不误报无韵
    rhymed = """【主歌1】雨落渡口那座山
他守着江水一年年
风从桥头吹过来
船桨横在石阶边
天没亮水线不断
像那年女儿走的那天
【副歌】他坐最低一档
等末班船过河
【主歌2】十年过去又一年
旧伞挂在竹竿边
【副歌】他坐最低一档
等末班船过河"""
    checks2 = _validate_lyrics(rhymed)
    assert not any("无韵" in c for c in checks2), "同辙押韵不应误报无韵"



def test_validate_lyrics_flags_abstract_personification() -> None:
    """抽象赋义检测：自然物+心理动词（草认得/山记得）→ 作者赋义拦截；可感拟人不误报。"""
    from app.api.v1.generations.music import _severe_checks, _validate_lyrics

    abstract = """【主歌1】天没亮 套鞋踩响碎石
帆布邮包压着右肩
草认得她的脚
山记得那年的事
【副歌】公路一修到村口
山路就开始长草
【主歌2】她走了四十年
草认得她的脚"""
    checks = _validate_lyrics(abstract)
    assert any("抽象赋义" in c for c in checks), "概念化拟人（草认得）应被拦截"
    assert _severe_checks(checks), "抽象赋义应触发自动重写"

    # 可感拟人：草弯腰 / 风把信纸吹到门槛（有画面）不误报
    concrete = """【主歌1】天没亮 套鞋踩响碎石
风一上坡 草就弯腰
露水打湿她的裤脚
她数着石阶 一级一级
【副歌】公路修到村口
山路开始长草
【主歌2】风把信纸吹到门槛
她蹲下来 捡起又放回"""
    checks2 = _validate_lyrics(concrete)
    assert not any("抽象赋义" in c for c in checks2), "可感拟人不应误报抽象赋义"



# ---------- 风格检测与写歌质量闭环 ----------


def test_detect_style_matches_theme() -> None:
    """风格检测：主题文本里的风格词 → 规范风格名；未命中返回空串（自由决定）。"""
    from app.api.v1.generations.music import _detect_style

    assert _detect_style("为矿工清晨写一首叙事民谣") == "民谣"
    assert _detect_style("古风：写一首江湖侠客的歌") == "古风"
    assert _detect_style("用电子合成器做一首夜店舞曲") == "电子"
    assert _detect_style("治愈系轻音乐，抚慰失眠的人") == "治愈系"
    assert _detect_style("纯场景描写，无风格倾向") == ""
    # 显式风格优先于主题检测（SSE 版 req.style 非空时不走检测）
    assert _detect_style("") == ""


# 合规歌词样本（260+ 字、段落句数达标、无 severe 问题）——compose 不重写测试用
_CLEAN_LYRICS = (
    "【主歌1】天没亮，路灯下卖粥的掀开锅盖\n"
    "白汽扑上玻璃，糊了半扇窗\n"
    "他把米汤撇进桶，锅底刮三遍\n"
    "末班车过站台，灯晃了一下\n"
    "那年她也坐这班，多看了两眼\n"
    "粥勺磕在缸沿，响一声数一声\n"
    "蒸汽顶得锅盖嗒嗒响，像有人敲门\n"
    "【预副歌】站台灯灭又亮\n"
    "粥还温着，人还没来\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "他把粥温着，像温着一句话\n"
    "【主歌2】收摊时剩粥倒给流浪猫\n"
    "猫不来，粥凉在桶里没人喝\n"
    "早班车灯扫过，他背过身擦碗\n"
    "街对过那盏灯，昨晚还亮着\n"
    "保温杯搁在挡位旁，茶垢一圈圈\n"
    "他数着日子，像数粥里的米粒\n"
    "路灯下他蹲着，把粥碗摆正\n"
    "碗底那圈豁口，他拿胶布缠了三道\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "他把粥温着，像温着一句话\n"
    "【桥段】他说，明天还来，天总会亮的\n"
    "抹布搭在缸沿，像个人还在等\n"
    "那碗粥凉了又热，热了又凉\n"
    "汽笛远了，他把灯调暗一档\n"
    "灶台上的钟，走到四点差一刻\n"
    "【预副歌】天快亮，粥又热了一遍\n"
    "那句话，他始终没问出口\n"
    "【主歌3】后半夜翻出那张旧车票\n"
    "票根折角，写着下夜班\n"
    "他擦了三遍，又放回信封\n"
    "天快亮时，粥又煮上一锅\n"
    "像那年她走时没说的那句话\n"
    "信封上的邮戳，他看了二十年\n"
    "【副歌】雾漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "他把粥温着，像温着一句话"
)
async def test_compose_rewrites_on_severe_checks(client, user_token) -> None:
    """写歌质量闭环：空洞赞颂/作文腔触发自动重写一轮；重写后返回修正稿 + checks。"""
    import app.api.v1.generations.music as music_mod

    hollow = {
        "title": "空歌",
        "style_zh": "流行",
        "style_en": "pop",
        "lyrics": (
            "【主歌1】跟着梦想的脚步，在时代的光芒里前行\n"
            "我们握紧双手的力量，把希望种进远方\n"
            "【副歌】呼吸着温热的风，悄悄把梦想点亮\n仿佛一切都美好，灿烂的明天在闪耀\n"
            "【主歌2】梦想的力量，像星火一样燃烧\n我们把希望，种在灿烂的远方\n"
            "【桥段】温柔的目光里，藏着美好的救赎\n"
            "【副歌】呼吸着温热的风，悄悄把梦想点亮\n仿佛一切都美好，灿烂的明天在闪耀"
        ),
        "tips": "x",
    }
    clean_lyrics = _CLEAN_LYRICS
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.side_effect = [
        type("R", (), {"content": json.dumps(hollow)})(),
        type(
            "R",
            (),
            {"content": json.dumps({**hollow, "lyrics": clean_lyrics})},
        )(),
    ]
    fake_resolver.model = "mock"
    with patch("app.api.v1.generations.music.resolve_text_provider", return_value=fake_resolver):
        data = await music_mod.compose_song(
            type("Req", (), {"theme": "歌颂劳动者", "style": "流行", "mood": "激昂",
                              "language": "中文", "verse_count": 2, "model": ""})(),
            None,  # type: ignore[arg-type]
            "u1",  # type: ignore[arg-type]
        )
    assert data["rewrote"] is True, "严重问题应触发自动重写"
    assert "空洞赞颂" not in "\n".join(data["checks"]), "重写后不应再出现空洞赞颂"
    assert "【主歌1】" in data["lyrics"]
    assert fake_resolver.provider.generate.await_count == 2


async def test_compose_no_rewrite_when_clean(client, user_token) -> None:
    """写歌质量闭环：合规歌词不触发重写（1 次调用），checks 仅轻提示。"""
    import app.api.v1.generations.music as music_mod

    clean = {
        "title": "晨雾",
        "style_zh": "民谣",
        "style_en": "folk",
        "lyrics": _CLEAN_LYRICS,
        "tips": "x",
    }
    fake_resolver = AsyncMock()
    fake_resolver.provider.generate.return_value = type(
        "R", (), {"content": json.dumps(clean)}
    )()
    fake_resolver.model = "mock"
    with patch("app.api.v1.generations.music.resolve_text_provider", return_value=fake_resolver):
        data = await music_mod.compose_song(
            type("Req", (), {"theme": "晨雾里的粥摊", "style": "民谣", "mood": "温暖",
                              "language": "中文", "verse_count": 2, "model": ""})(),
            None,  # type: ignore[arg-type]
            "u1",  # type: ignore[arg-type]
        )
    assert data.get("rewrote") is None or data["rewrote"] is False, "合规歌词不应重写"
    assert "checks" in data
    assert fake_resolver.provider.generate.await_count == 1


