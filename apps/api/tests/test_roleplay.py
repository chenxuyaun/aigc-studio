"""角色扮演服务测试：PNG 解析 + system prompt 构造。"""

from __future__ import annotations

import base64
import io
import json

import pytest
from app.services import roleplay
from PIL import Image, PngImagePlugin


def _make_card_png(card: dict) -> bytes:
    buf = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text(
        "chara", base64.b64encode(json.dumps(card, ensure_ascii=False).encode()).decode()
    )
    Image.new("RGB", (64, 64), (100, 120, 140)).save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def test_parse_character_png_roundtrip() -> None:
    card = {
        "name": "露娜",
        "description": "魔法黑猫",
        "personality": "温柔",
        "scenario": "咖啡馆",
        "first_mes": "要来一杯吗？",
        "mes_example": "用户：你好。露娜：喵~",
    }
    parsed = roleplay.parse_character_png(_make_card_png(card))
    assert parsed["name"] == "露娜"
    assert parsed["first_mes"] == "要来一杯吗？"
    assert parsed["mes_example"]


def test_parse_character_png_invalid() -> None:
    assert roleplay.parse_character_png(b"not a png") == {}
    assert roleplay.parse_character_png(_make_card_png({"no": "fields"})) == {}


def test_parse_character_png_v2_nested() -> None:
    """兼容 V2 嵌套 data 结构。"""
    png = _make_card_png(
        {"name": "外层", "data": {"name": "内层名", "first_mes": "内层开场"}}
    )
    parsed = roleplay.parse_character_png(png)
    assert parsed["name"] == "外层"  # 顶层优先
    png2 = _make_card_png({"data": {"name": "内层名", "first_mes": "内层开场"}})
    parsed2 = roleplay.parse_character_png(png2)
    assert parsed2["name"] == "内层名"


@pytest.mark.anyio
async def test_build_system_prompt_with_lore(monkeypatch: pytest.MonkeyPatch) -> None:
    """system prompt 含角色设定 + 世界书命中。"""
    card = {
        "name": "露娜",
        "description": "魔法黑猫",
        "personality": "温柔",
        "scenario": "咖啡馆",
        "first_mes": "要来一杯吗？",
    }

    class _FakeEntry:
        keyword = "魔法"
        content = "这个世界里魔法需要月亮石驱动"

    async def fake_match(db: object, name: str, msgs: list[str]) -> list[str]:
        return ["魔法：这个世界里魔法需要月亮石驱动"]

    monkeypatch.setattr(roleplay, "_match_lore", fake_match)
    prompt = await roleplay._build_system_prompt(None, card, ["我今天用魔法了"])  # type: ignore[arg-type]
    assert "露娜" in prompt
    assert "魔法黑猫" in prompt
    assert "月亮石" in prompt
    assert "开场白" in prompt


def test_list_characters_query_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """列表查询字段完整。"""
    from app.services import roleplay as rp

    class _FakeAsset:
        id = "a1"
        filename = "character-abc.png"
        created_at = None

    class _FakeResult:
        def scalars(self) -> _FakeResult:
            return self

        def all(self) -> list[_FakeAsset]:
            return [_FakeAsset()]

    class _FakeDB:
        async def execute(self, stmt: object) -> _FakeResult:
            return _FakeResult()

    async def fake(db: object, user_id: str) -> list[dict]:
        return await rp.list_characters(db, user_id)

    items = __import__("asyncio").run(fake(_FakeDB(), "u1"))
    assert items[0]["asset_id"] == "a1"
    # 签名 URL：content 路径 + exp/sig 查询参数（无需 JWT 即可 <img> 直出）
    url = items[0]["url"]
    assert url.startswith("/api/v1/assets/a1/content?")
    assert "exp=" in url and "sig=" in url


def test_extract_mood() -> None:
    """情绪标签提取 + 正文清理。"""
    from app.services.roleplay import _mood_delta, extract_mood

    clean, mood = extract_mood("今天很开心呢 [情绪:开心]")
    assert mood == "开心"
    assert "情绪" not in clean

    clean2, mood2 = extract_mood("没有标签的回复")
    assert mood2 == ""
    assert clean2 == "没有标签的回复"

    assert _mood_delta("开心") == 1
    assert _mood_delta("生气") == -1
    assert _mood_delta("平静") == 0
