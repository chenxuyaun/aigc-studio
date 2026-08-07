"""世界书引擎 + 宏系统 + 会话导出导入测试（SillyTavern 功能融入）。"""

from __future__ import annotations

import json

import pytest
from app.services import macros, sessions
from app.services.worldbook import match_worldbook


class _Entry:
    def __init__(self, **kw) -> None:  # type: ignore[no-untyped-def]
        self.id = kw.pop("id", "e1")
        self.keywords = json.dumps(kw.pop("keywords", []), ensure_ascii=False)
        self.keyword = kw.pop("keyword", "")
        self.keysecondary = json.dumps(kw.pop("keysecondary", []), ensure_ascii=False)
        self.content = kw.pop("content", "设定内容")
        self.constant = kw.pop("constant", False)
        self.selective = kw.pop("selective", True)
        self.selective_logic = kw.pop("selective_logic", "AND_ANY")
        self.position = kw.pop("position", "before")
        self.order_value = kw.pop("order_value", 100)
        self.depth = kw.pop("depth", 4)
        self.role = kw.pop("role", "system")
        self.scan_depth = None
        self.case_sensitive = kw.pop("case_sensitive", False)
        self.match_whole_words = kw.pop("match_whole_words", False)
        self.probability = kw.pop("probability", 100)
        self.enabled = kw.pop("enabled", True)


# ==== 世界书引擎 ====

def test_keyword_match_and_position() -> None:
    entries = [
        _Entry(id="a", keywords=["月亮石"], content="月亮石是魔法之源", position="before"),
        _Entry(id="b", keywords=["月亮石"], content="后置设定", position="after"),
        _Entry(id="c", keywords=["不存在"], content="不该命中"),
    ]
    result = match_worldbook(entries, ["我今天捡到一块月亮石"])
    assert "月亮石是魔法之源" in result.before
    assert "后置设定" in result.after
    assert "不该命中" not in result.before
    assert "不该命中" not in result.after
    assert result.activated == ["a", "b"]


def test_constant_entry_always_active() -> None:
    entries = [
        _Entry(id="c1", keywords=[], constant=True, content="常驻设定"),
        _Entry(id="c2", keywords=["魔法"], content="关键词设定"),
    ]
    result = match_worldbook(entries, ["今天天气不错"])
    assert "常驻设定" in result.before
    assert "关键词设定" not in result.before


def test_whole_word_and_case_sensitive() -> None:
    entries = [
        _Entry(id="w", keywords=["cat"], match_whole_words=True, content="整词命中"),
        _Entry(id="c", keywords=["CAT"], case_sensitive=True, content="大小写命中"),
    ]
    # "cat" 是 "concatenate" 的子串 → 整词不命中
    assert "整词命中" not in match_worldbook(entries, ["concatenate 函数"]).before
    assert "整词命中" in match_worldbook(entries, ["a cat sat"]).before
    # 大小写敏感：小写 cat 不命中 CAT
    assert "大小写命中" not in match_worldbook(entries, ["a cat sat"]).before
    assert "大小写命中" in match_worldbook(entries, ["A CAT sat"]).before


def test_regex_keyword() -> None:
    entries = [
        _Entry(id="r", keywords=["/月\\d+号/"], content="正则命中"),
        _Entry(id="x", keywords=["/bad[/"], content="坏正则"),
    ]
    result = match_worldbook(entries, ["我在 8月12号 出发"])
    assert "正则命中" in result.before
    assert "坏正则" not in result.before


def test_selective_secondary_keyword() -> None:
    entries = [
        _Entry(
            id="s1", keywords=["魔法"], keysecondary=["月亮石"],
            selective=True, selective_logic="AND_ANY", content="选择性命中",
        ),
        _Entry(
            id="s2", keywords=["魔法"], keysecondary=["月亮石"],
            selective=True, selective_logic="AND_ALL", content="全都要",
        ),
    ]
    result = match_worldbook(entries, ["魔法真有趣，月亮石很亮"])
    assert "选择性命中" in result.before
    assert "全都要" in result.before
    result2 = match_worldbook(entries, ["魔法真有趣"])
    assert "选择性命中" not in result2.before
    assert "全都要" not in result2.before


def test_order_sorting_and_at_depth() -> None:
    entries = [
        _Entry(
            id="d1", keywords=["月亮石"], order_value=50,
            position="atDepth", depth=3, content="深注入",
        ),
        _Entry(id="o1", keywords=["月亮石"], order_value=200, content="高优先级"),
        _Entry(id="o2", keywords=["月亮石"], order_value=100, content="中优先级"),
    ]
    result = match_worldbook(entries, ["月亮石"])
    assert result.before == ["高优先级", "中优先级"]
    assert [h.depth for h in result.at_depth] == [3]
    assert result.at_depth[0].content == "深注入"


def test_probability_and_disabled() -> None:
    import random

    entries = [
        _Entry(id="p0", keywords=["月亮石"], probability=0, content="永不触发"),
        _Entry(id="p100", keywords=["月亮石"], probability=100, content="必然触发"),
        _Entry(id="off", keywords=["月亮石"], enabled=False, content="被禁用"),
    ]
    result = match_worldbook(entries, ["月亮石"], rng=random.Random(42))
    assert "永不触发" not in result.before
    assert "必然触发" in result.before
    assert "被禁用" not in result.before


def test_budget_limit() -> None:
    entries = [
        _Entry(id=f"b{i}", keywords=["月亮石"], content="x" * 200, order_value=100 - i)
        for i in range(10)
    ]
    result = match_worldbook(entries, ["月亮石"], budget_tokens=300)
    assert len(result.before) == 3  # 每条 ~100 token，预算 300 → 3 条


# ==== 宏系统 ====

def test_macros_names_and_fields() -> None:
    ctx = {
        "char": {"name": "露娜", "description": "魔法黑猫"},
        "user": "小明",
        "group": "露娜、小狼",
    }
    assert macros.substitute("我是{{char}}，你是{{user}}", ctx) == "我是露娜，你是小明"
    assert macros.substitute("{{charDescription}}", ctx) == "魔法黑猫"
    assert macros.substitute("{{group}}", ctx) == "露娜、小狼"
    assert macros.substitute("<USER> 和 <CHAR>", ctx) == "小明 和 露娜"
    # 未识别宏保留原样
    assert macros.substitute("{{unknown}}", ctx) == "{{unknown}}"


def test_macros_random_pick_roll() -> None:
    ctx = {"user": "小明", "char": {"name": "露娜"}, "seed": "s1"}
    v = macros.substitute("{{random::A::B}}", ctx)
    assert v in ("A", "B")
    # pick 确定性：同 seed 同位置结果一致
    p1 = macros.substitute("{{pick::甲::乙::丙}}", ctx)
    p2 = macros.substitute("{{pick::甲::乙::丙}}", ctx)
    assert p1 == p2
    assert p1 in ("甲", "乙", "丙")
    # 骰子
    r = macros.substitute("{{roll::1d6}}", ctx)
    assert r.isdigit()
    assert 1 <= int(r) <= 6
    r2 = macros.substitute("{{roll::2d6+1}}", ctx)
    assert r2.isdigit()
    assert 3 <= int(r2) <= 13


def test_macros_time_and_tools() -> None:
    ctx = {"input": "你好", "last_message": "再见"}
    assert macros.substitute("{{newline::2}}", ctx) == "\n\n"
    assert macros.substitute("{{input}}|{{lastMessage}}", ctx) == "你好|再见"
    t = macros.substitute("{{time}}", {})
    assert ":" in t
    d = macros.substitute("{{date}}", {})
    assert len(d) == 10


# ==== 会话 ====

class _FakeChat:
    def __init__(self, **kw) -> None:  # type: ignore[no-untyped-def]
        self.id = kw.get("id", "c1")
        self.title = kw.get("title", "会话")
        self.character_asset_ids = kw.get("character_asset_ids", "[]")
        self.group = kw.get("group", False)
        self.messages = kw.get("messages", "[]")
        self.model = kw.get("model", "")
        self.temperature = kw.get("temperature")
        self.max_tokens = kw.get("max_tokens")
        self.top_p = kw.get("top_p")
        self.settings = kw.get("settings", "{}")
        self.created_at = None
        self.updated_at = None


def test_export_jsonl_format() -> None:
    chat = _FakeChat(
        messages=json.dumps(
            [
                {"role": "user", "content": "你好", "created_at": "2026-08-03T10:00:00+00:00"},
                {
                    "role": "assistant", "content": "喵~", "mood": "开心",
                    "created_at": "2026-08-03T10:00:01+00:00",
                },
            ],
            ensure_ascii=False,
        ),
        character_asset_ids=json.dumps(["a1"]),
    )
    text = sessions.export_jsonl(chat)
    lines = text.splitlines()
    assert len(lines) == 3
    meta = json.loads(lines[0])
    assert "chat_metadata" in meta
    assert meta["is_group"] is False
    msg1 = json.loads(lines[1])
    assert msg1["is_user"] is True
    assert msg1["mes"] == "你好"
    msg2 = json.loads(lines[2])
    assert msg2["is_user"] is False
    assert msg2["mes"] == "喵~"


def test_import_jsonl_roundtrip() -> None:
    chat = _FakeChat(
        messages=json.dumps(
            [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "喵~"},
            ],
            ensure_ascii=False,
        )
    )
    text = sessions.export_jsonl(chat)
    class _DB:  # 最小 fake：import_jsonl 只调 db.add
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

    imported = sessions.import_jsonl(_DB(), "u1", text)  # type: ignore[arg-type]
    assert imported is not None
    msgs = sessions.chat_messages(imported)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "你好"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "喵~"


def test_messages_load_empty() -> None:
    assert sessions.chat_messages(_FakeChat()) == []
    assert sessions.chat_messages(_FakeChat(messages="not json")) == []


# ==== atDepth 深度注入接入 prompt 管线 ====

@pytest.mark.anyio
async def test_build_prompt_at_depth_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    """atDepth 世界书条目按深度插入历史中部（距末尾第 N 条之后）。"""
    from app.services import roleplay as rp

    class _FakeEntry:
        id = "d1"
        keywords = json.dumps(["月亮石"])
        keyword = ""
        keysecondary = "[]"
        content = "月亮石在午夜会发光"
        constant = False
        selective = False
        selective_logic = "AND_ANY"
        position = "atDepth"
        order_value = 100
        depth = 2
        role = "system"
        scan_depth = None
        case_sensitive = False
        match_whole_words = False
        probability = 100
        enabled = True

    async def fake_load(db: object, uid: str, names: list[str]) -> list[object]:
        return [_FakeEntry()]

    monkeypatch.setattr(rp, "_load_lore_entries", fake_load)

    card = {"name": "露娜", "description": "魔法黑猫", "personality": "温柔", "scenario": "咖啡馆"}
    messages = [
        {"role": "user", "content": "m1"},
        {"role": "assistant", "content": "m2"},
        {"role": "user", "content": "m3 月亮石"},
        {"role": "assistant", "content": "m4"},
    ]
    _, user_prompt, activated, _ = await rp._build_prompt(  # type: ignore[arg-type]
        None, "u1", [("a1", card)], messages
    )
    # 激活数正确
    assert activated == ["d1"]
    # 深度注入文本出现且位置在历史中部：m2 之后、m3 之前
    assert "月亮石在午夜会发光" in user_prompt
    idx_m2 = user_prompt.find("m2")
    idx_inject = user_prompt.find("月亮石在午夜会发光")
    idx_m3 = user_prompt.find("m3 月亮石")
    assert idx_m2 < idx_inject < idx_m3


@pytest.mark.anyio
async def test_build_prompt_continue_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """continue 模式：最后一条角色回复截断保留尾段 + 续写指令。"""
    from app.services import roleplay as rp

    async def fake_load(db: object, uid: str, names: list[str]) -> list[object]:
        return []

    monkeypatch.setattr(rp, "_load_lore_entries", fake_load)

    card = {"name": "露娜", "description": "魔法黑猫", "personality": "温柔", "scenario": "咖啡馆"}
    long_reply = "这是一条很长的回复" + "。内容很多" * 20
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": long_reply},
    ]
    _, user_prompt, _, _ = await rp._build_prompt(  # type: ignore[arg-type]
        None, "u1", [("a1", card)], messages, continue_mode=True
    )
    assert "继续写下去" in user_prompt
    # 截断后只保留尾段（长度 < 原长）
    assert long_reply not in user_prompt
    # 普通模式无续写指令
    _, normal_prompt, _, _ = await rp._build_prompt(  # type: ignore[arg-type]
        None, "u1", [("a1", card)], messages
    )
    assert "继续写下去" not in normal_prompt


def test_alternate_greetings_selection() -> None:
    """首轮开场白：first_mes 与备用开场白随机候选。"""
    from app.services import roleplay as rp

    # 无备用 → 用 first_mes
    card = {"name": "露娜", "first_mes": "要来一杯吗？", "alternate_greetings": []}
    alts = rp._greeting_candidates(card)
    assert alts == ["要来一杯吗？"]
    # 有备用 → 全部候选
    card2 = {"name": "露娜", "first_mes": "A", "alternate_greetings": ["B", "C"]}
    alts2 = rp._greeting_candidates(card2)
    assert set(alts2) == {"A", "B", "C"}
    # 空开场白
    assert (
        rp._greeting_candidates({"name": "露娜", "first_mes": "", "alternate_greetings": []})
        == []
    )


def test_sessions_remove_message() -> None:
    """按索引删除消息。"""
    import json as _json

    chat = _FakeChat(
        messages=_json.dumps(
            [
                {"role": "user", "content": "m1"},
                {"role": "assistant", "content": "m2"},
                {"role": "user", "content": "m3"},
            ],
            ensure_ascii=False,
        )
    )
    assert sessions.remove_message(chat, 1) is True
    msgs = sessions.chat_messages(chat)
    assert [m["content"] for m in msgs] == ["m1", "m3"]
    assert sessions.remove_message(chat, 5) is False
    assert sessions.remove_message(chat, -1) is False


@pytest.mark.anyio
async def test_roleplay_chat_upstream_error_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游 429/异常 → 友好 error 而非抛异常。"""
    from app.services import roleplay as rp

    class _FakeProvider:
        async def generate(self, *a: object, **kw: object) -> object:
            raise RuntimeError("上游返回 429: rate limited")

    class _FakeResolved:
        provider = _FakeProvider()
        model = "mock"

    async def fake_resolve(db: object, model: str) -> object:
        return _FakeResolved()

    async def fake_load_cards(db: object, uid: str, ids: list[str]) -> list[tuple[str, dict]]:
        return [("a1", {"name": "露娜", "description": "x", "personality": "y", "scenario": "z"})]

    monkeypatch.setattr(rp, "_load_cards", fake_load_cards)

    async def fake_regex(db: object, uid: str) -> list[object]:
        return []

    async def fake_lore(db: object, uid: str, names: list[str]) -> list[object]:
        return []

    monkeypatch.setattr(rp, "_load_regex_scripts", fake_regex)
    monkeypatch.setattr(rp, "_load_lore_entries", fake_lore)
    monkeypatch.setattr(rp, "resolve_text_provider", fake_resolve)

    result = await rp.roleplay_chat(None, "u1", ["a1"], [{"role": "user", "content": "hi"}])  # type: ignore[arg-type]
    assert "error" in result
    assert "429" in result["error"]


def test_yaml_character_card_import() -> None:
    """YAML 角色卡导入（V1 字段）。"""
    from app.services.character_card import import_character_card

    yaml_text = """name: YAML猫
description: YAML 格式的角色卡
personality: 冷静
scenario: 图书馆
first_mes: 请安静看书。
"""
    result = import_character_card(yaml_text.encode("utf-8"))
    assert result is not None
    assert result["source"] == "yaml"
    assert result["card"]["name"] == "YAML猫"
    assert result["card"]["first_mes"] == "请安静看书。"
    assert result["png"][:8] == b"\x89PNG\r\n\x1a\n"


def test_lorebook_st_roundtrip() -> None:
    """ST lorebook JSON 导出 → 再导入 → 字段保留。"""
    from app.services.worldbook import lorebook_from_st, lorebook_to_st

    class _E:
        keywords = json.dumps(["月亮石"])
        keyword = ""
        keysecondary = json.dumps(["魔法"])
        content = "月亮石是魔法之源"
        constant = True
        selective = True
        selective_logic = "AND_ANY"
        position = "after"
        order_value = 50
        depth = 3
        role = "user"
        probability = 80
        enabled = True
        case_sensitive = False
        match_whole_words = True

    book = lorebook_to_st([_E()], "测试书")
    assert book["name"] == "测试书"
    e0 = book["entries"]["0"]
    assert e0["key"] == ["月亮石"]
    assert e0["constant"] is True
    assert e0["position"] == 1  # after
    assert e0["role"] == 1  # user
    assert e0["selectiveLogic"] == 0

    entries = lorebook_from_st(book)
    assert len(entries) == 1
    e = entries[0]
    assert e["keywords"] == ["月亮石"]
    assert e["constant"] is True
    assert e["position"] == "after"
    assert e["role"] == "user"
    assert e["selective_logic"] == "AND_ANY"
    assert e["match_whole_words"] is True


@pytest.mark.anyio
async def test_memory_summary_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    """记忆摘要注入 system prompt。"""
    from app.services import roleplay as rp

    async def fake_lore(db: object, uid: str, names: list[str]) -> list[object]:
        return []

    monkeypatch.setattr(rp, "_load_lore_entries", fake_lore)

    card = {"name": "露娜", "description": "魔法黑猫", "personality": "温柔", "scenario": "咖啡馆"}
    msgs = [{"role": "user", "content": "m1"}, {"role": "assistant", "content": "m2"}]
    system_prompt, _, _, _ = await rp._build_prompt(  # type: ignore[arg-type]
        None, "u1", [("a1", card)], msgs, memory_summary="他们去了月亮湖"
    )
    assert "记忆摘要" in system_prompt
    assert "月亮湖" in system_prompt
    # 无摘要时不注入
    system_prompt2, _, _, _ = await rp._build_prompt(  # type: ignore[arg-type]
        None, "u1", [("a1", card)], msgs
    )
    assert "记忆摘要" not in system_prompt2


def test_memory_settings_helpers() -> None:
    """会话 settings 读写。"""
    chat = _FakeChat(settings='{"summary": "旧摘要"}')
    assert sessions.get_settings(chat).get("summary") == "旧摘要"
    sessions.set_settings(chat, {"summary": "新摘要", "last_summarized_index": 5})
    assert json.loads(chat.settings)["last_summarized_index"] == 5
    assert sessions.get_settings(_FakeChat(settings="not json")) == {}


@pytest.mark.anyio
async def test_branch_chat() -> None:
    """会话分支：从第 N 条消息分叉。"""
    from app.services import sessions as _s

    chat = _FakeChat(
        messages=json.dumps(
            [
                {"role": "user", "content": "m1"},
                {"role": "assistant", "content": "m2"},
                {"role": "user", "content": "m3"},
            ],
            ensure_ascii=False,
        ),
        character_asset_ids=json.dumps(["a1"]),
        model="m",
        temperature=0.7,
        max_tokens=512,
        top_p=None,
        settings='{}',
    )

    class _DB:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def flush(self) -> None:
            return None

    branch = await _s.branch_chat(_DB(), "u1", chat, 1)  # type: ignore[arg-type]
    assert branch is not None
    msgs = _s.chat_messages(branch)
    assert [m["content"] for m in msgs] == ["m1", "m2"]
    assert branch.model == "m"
    # 越界
    bad = await _s.branch_chat(_DB(), "u1", chat, 99)  # type: ignore[arg-type]
    assert bad is None
