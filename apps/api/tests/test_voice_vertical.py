"""Voice 垂直接入测试：story/roundtable/music 出稿后对照用户文风档案的 AI 腔自检。

覆盖：
- roundtable `_validate_final`：传 voice_dna 命中个人忌讳；不传退化为通用规则
- music engine `compose_song`/`roundtable_single`：voice_dna 命中 → checks 追加个人忌讳；
  无 user_id 时静默跳过（行为与旧版一致）
- story `stream_chapter_sse`：done 事件 ai_voice 含 voice_avoid（端到端，mock provider）
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.applications.roundtable_service import _validate_final

# ===== roundtable._validate_final（纯函数）=====


def _long_body() -> str:
    """拼一段超过 copy 领域最低字数（300）的正文（不含任何 AI 腔词）。"""
    base = "老陈把半袋钱塞进麻袋口，像潮声在胸口滚。货摊支在桥洞下，铁皮炉子烧着隔夜的煤。"
    while len(base) < 330:
        base += "他把伞骨抵在膝盖上拗直，铁盒里的铜板磕得脆响。"
    return base


def test_roundtable_validate_final_voice_dna_hits_avoid() -> None:
    """传入 voice_dna（avoid 含「赋能」）时，定稿含个人忌讳表达 → AI 腔警告命中。"""
    final = {
        "title": "桥东粥铺",
        "content": "为顾客赋能，让清晨更有温度。" + "众所周知，这家店开了二十年。" + _long_body(),
        "style": "市井",
    }
    checks = _validate_final("copy", final, voice_dna={"avoid": ["赋能"]})
    warn = next((c for c in checks if "AI 腔过重" in c), "")
    assert warn, f"应命中 AI 腔（含个人忌讳）警告，实际: {checks}"
    assert "赋能" in warn


def test_roundtable_final_without_dna_legacy() -> None:
    """不传 voice_dna 时退化为通用规则（个人忌讳不参与判定，也不误报）。"""
    final = {
        "title": "桥东粥铺",
        "content": "顾客觉得这里有新体验，让清晨更有温度。" + _long_body(),
        "style": "市井",
    }
    checks = _validate_final("copy", final)
    assert all("AI 腔过重" not in c for c in checks), checks


# ===== music engine：compose_song / roundtable_single =====

# 合规歌词样本（test_music_works 同款：结构完整、不触发重写）
_CLEAN_LYRICS = (
    "【主歌1】天没亮，路灯下卖粥的掀开锅盖\n"
    "白汽扑上玻璃，糊了半扇窗\n"
    "他把米汤撇进桶，锅底刮三遍\n"
    "末班车过站台，灯晃了一下\n"
    "那年她也坐这班，多看了两眼\n"
    "粥勺磕在缸沿，响一声数一声\n"
    "蒸汽顶得锅盖达达响，像有人敲门\n"
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
    "【副歌】粥漫过山脊，我端着碗等天亮\n"
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
    "【副歌】粥漫过山脊，我端着碗等天亮\n"
    "锅盖响了三声，他说多添碗汤\n"
    "汽笛穿过巷口，她还没回来\n"
    "他把粥温着，像温着一句话"
)


def _lyrics_result(lyrics: str):
    return type("R", (), {"content": json.dumps({"title": "桥东粥铺", "style_zh": "市井", "lyrics": lyrics})})()


@pytest.mark.asyncio
async def test_compose_song_voice_dna_hits_personal_avoid() -> None:
    """compose_song 带 user_id：文风档案 avoid 命中 → checks 含「文风档案忌讳」，不触发自动重写。"""
    import app.core.runtime.music.engine as engine

    lyrics = _CLEAN_LYRICS.replace("路灯下卖粥的掀开锅盖", "为顾客赋能的摊主掀开锅盖")  # 含个人忌讳词
    res = AsyncMock()
    res.provider.generate.return_value = _lyrics_result(lyrics)
    res.model = "mock"
    with patch.object(engine, "resolve_text_provider", return_value=res), patch.object(
        engine, "_load_voice_dna", new=AsyncMock(return_value={"avoid": ["赋能"]})
    ) as load_dna:
        req = SimpleNamespace(theme="桥东粥铺", style="市集", mood="温暖", language="中文",
                              verse_count=2, model="")
        data = await engine.compose_song(None, req, user_id="u1")
    load_dna.assert_awaited_once()
    assert any("文风档案忌讳" in c for c in data["checks"]), data["checks"]
    # AI 腔只是警告：歌词结构完整时应只调用一次（未触发自动重写）
    assert data.get("rewrote") is None


@pytest.mark.asyncio
async def test_compose_song_no_user_no_voice_load() -> None:
    """不传 user_id：不查文风档案（无 DB 查询），checks 只含结构质检。"""
    import app.core.runtime.music.engine as engine

    res = AsyncMock()
    res.provider.generate.return_value = _lyrics_result(_CLEAN_LYRICS)
    res.model = "mock"
    fake_profile = AsyncMock()
    with patch.object(engine, "resolve_text_provider", return_value=res), patch.object(
        engine, "_load_voice_dna", new=AsyncMock()
    ) as load_dna, patch(
        "app.applications.voice_service.get_profile", fake_profile
    ):
        req = SimpleNamespace(theme="桥东粥铺", style="市集", mood="平和", language="zh",
                              verse_count=2, model="")
        data = await engine.compose_song(None, req)
    fake_profile.assert_not_awaited()  # 无 user_id 不触发档案查询
    assert not any(("文风档案忌讳" in c) or ("AI 腔过重" in c) for c in data["checks"])


@pytest.mark.asyncio
async def test_roundtable_single_voice_dna() -> None:
    """roundtable_single 带 user_id：对照档案做 AI 腔自检。"""
    import app.core.runtime.music.engine as engine

    res = AsyncMock()
    res.provider.generate.return_value = _lyrics_result(_CLEAN_LYRICS)
    res.model = "mock"
    with patch.object(engine, "resolve_text_provider", return_value=res), patch.object(
        engine, "_load_voice_dna", new=AsyncMock(return_value={"avoid": ["路灯"]})
    ):
        data = await engine.roundtable_single(
            None, theme="桥东粥铺", style="", mood="", model="", user_id="u1"
        )
    assert any("文风档案忌讳" in c for c in data["checks"]), data["checks"]


# ===== story 流式章节：done 事件 ai_voice 带个人档案 =====

@pytest.mark.asyncio
async def test_story_done_event_includes_voice_issues(monkeypatch) -> None:
    """story 流式生成：用户档案 avoid 命中 Mock 文本词 → done.ai_voice 含 voice_avoid。

    端到端不打 mock：MockTextProvider 输出含「示例」词，档案 avoid 含「示例」即命中。
    """
    from app.core.database import AsyncSessionLocal
    from app.core.runtime.story import generation as gen

    proj = SimpleNamespace(id="p1", user_id="u1", character_asset_ids="[]")
    chap = SimpleNamespace(id="c1", user_id="u1", chapter_no=1, content="", word_count=0,
                           model="", status="")

    async def fake_get_project(db, uid, pid):
        return proj

    async def fake_get_chapter(db, uid, cid):
        return chap

    async def fake_cards(db, uid, ids):
        return [("阿夜", {"name": "阿夜"})]

    async def fake_prompt(db, uid, project, chapter, cards, instruction=""):
        return ("system", "user", SimpleNamespace(activated=[]))

    async def fake_scripts(db, uid):
        return []

    async def fake_profile(db, uid):
        return SimpleNamespace(voice_dna={"avoid": ["示例"], "name": "测试档案"})

    monkeypatch.setattr(gen.story_forge, "get_project", fake_get_project)
    monkeypatch.setattr(gen.story_forge, "get_chapter", fake_get_chapter)
    monkeypatch.setattr(gen.rp, "_load_cards", fake_cards)
    monkeypatch.setattr(gen.story_forge, "_build_chapter_prompt", fake_prompt)
    monkeypatch.setattr(gen.rp, "_load_regex_scripts", fake_scripts)
    monkeypatch.setattr("app.applications.voice_service.get_profile", fake_profile)

    async with AsyncSessionLocal() as db:
        done = None
        async for line in gen.stream_chapter_sse(db, "u1", "c1", project_id="p1"):
            if line.startswith("data: ") and '"type": "done"' in line:
                done = json.loads(line[6:])
    assert done is not None, "缺少 done 事件"
    voice_avoid = [i for i in done["ai_voice"] if i["kind"] == "voice_avoid"]
    assert voice_avoid, f"应命中个人忌讳：{done['ai_voice']}"
    assert "示例" in voice_avoid[0]["sample"]

# ===== ③ 自动提取时机：maybe_auto_extract 节流 =====

async def _seed_corpus(db, user_id: str, n: int = 12) -> None:
    from app.applications.voice_service import add_corpus

    for i in range(n):
        await add_corpus(
            db, user_id, "note", f"第{i}条想法：桥东的粥摊，五点四十的煤灰味。老陈说今天多加点姜。"
        )


@pytest.mark.asyncio
async def test_auto_extract_skips_when_corpus_too_small() -> None:
    """语料不足阈值时跳过（不建档、不跑提炼）。"""
    from app.core.database import AsyncSessionLocal
    from app.applications.voice_service import get_profile, maybe_auto_extract

    async with AsyncSessionLocal() as db:
        ok = await maybe_auto_extract(db, "u-autoskip")
    assert ok is False
    async with AsyncSessionLocal() as db:
        assert await get_profile(db, "u-autoskip") is None


@pytest.mark.asyncio
async def test_auto_extract_runs_when_corpus_ready(monkeypatch) -> None:
    """语料达标且无档案 → 自动提炼出 auto 档案（LLM 路径真实走通）。"""
    from app.core.database import AsyncSessionLocal
    from app.applications.voice_service import get_profile, maybe_auto_extract

    class _FakeLLM:
        async def generate(self, prompt, model, **kw) -> SimpleNamespace:
            return SimpleNamespace(
                content=(
                    '{"sentence_length": "short", "formality": "casual", '
                    '"avoid": ["赋能", "硬凑"], "preferred": ["短句"]}'
                )
            )

    async def _fake_resolve(db, model, **kw) -> SimpleNamespace:
        return SimpleNamespace(provider=_FakeLLM(), model="mock-llm")

    async with AsyncSessionLocal() as db:
        await _seed_corpus(db, "u-autofirst")
        monkeypatch.setattr(
            "app.applications.voice_service.resolve_text_provider", _fake_resolve
        )
        ok = await maybe_auto_extract(db, "u-autofirst")
    assert ok is True
    async with AsyncSessionLocal() as db:
        p = await get_profile(db, "u-autofirst")
    assert p is not None and p.source == "auto"
    assert p.voice_dna.get("avoid") == ["赋能", "硬凑"]  # LLM 提炼结果真实入库


@pytest.mark.asyncio
async def test_auto_extract_respects_manual_profile() -> None:
    """manual 档案永不覆盖（用户显式配置优先）。"""
    from app.core.database import AsyncSessionLocal
    from app.applications.voice_service import (
        get_profile,
        maybe_auto_extract,
        update_profile,
    )

    async with AsyncSessionLocal() as db:
        await update_profile(db, "u-autoor2", name="我亲手写的", dna={"avoid": ["赋能"]})
        await _seed_corpus(db, "u-autoor2")
        ok = await maybe_auto_extract(db, "u-autoor2")
        p = await get_profile(db, "u-autoor2")
    assert ok is False
    assert p is not None and p.source == "manual" and p.name == "我亲手写的"


@pytest.mark.asyncio
async def test_auto_extract_respects_cooldown(monkeypatch) -> None:
    """auto 档案 24h 冷却期内不重复提炼。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.applications.voice_service import (
        auto_extract_profile,
        maybe_auto_extract,
    )
    from app.data.models.voice import VoiceProfile

    async with AsyncSessionLocal() as db:
        await _seed_corpus(db, "u-autocool")
        async def _fuse_llm(*_a, **_k):
            raise RuntimeError("llm down")

        monkeypatch.setattr(
            "app.applications.voice_service.resolve_text_provider", _fuse_llm
        )
        p = await auto_extract_profile(db, "u-autocool")  # 走规则兜底建档
        await db.execute(
            update(VoiceProfile)
            .where(VoiceProfile.user_id == "u-autocool")
            .values(updated_at=datetime.now(timezone.utc).replace(tzinfo=None))
        )
        await db.commit()
        ok = await maybe_auto_extract(db, "u-autocool")  # 刚建 → 冷却中
    assert p is not None and ok is False


@pytest.mark.asyncio
async def test_extract_after_cooldown_refreshes(monkeypatch) -> None:
    """冷却期过后且语料在涨 → 重新提炼。"""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.applications.voice_service import (
        get_profile,
        maybe_auto_extract,
        _extract_dna_rules,
    )
    from app.data.models.voice import VoiceProfile

    from app.applications.voice_service import auto_extract_profile

    async with AsyncSessionLocal() as db:
        await _seed_corpus(db, "u-autorefresh")
        async def _fuse_llm(*_a, **_k):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(
            "app.applications.voice_service.resolve_text_provider", _fuse_llm
        )
        await auto_extract_profile(db, "u-autorefresh")  # 规则兜底建档
        await db.execute(
            update(VoiceProfile)
            .where(VoiceProfile.user_id == "u-autorefresh")
            .values(
                updated_at=(datetime.now(timezone.utc) - timedelta(hours=25)).replace(
                    tzinfo=None
                )
            )
        )
        await db.commit()
        ok = await maybe_auto_extract(db, "u-autorefresh")  # 已过 24h → 重新提炼
        p = await get_profile(db, "u-autorefresh")
    assert ok is True and p is not None and p.source == "auto"
