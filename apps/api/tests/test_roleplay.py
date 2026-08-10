"""角色扮演服务测试：PNG 解析 + system prompt 构造。"""

from __future__ import annotations

import base64
import io
import json

import pytest
from app.services import roleplay
from PIL import Image, PngImagePlugin

from tests.conftest import TestingSessionLocal


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
    assert "exp=" in url
    assert "sig=" in url


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


def test_speaker_lines_extracts_by_name() -> None:
    """群聊回复按角色名前缀拆台词。"""
    from app.services.roleplay import _speaker_lines

    reply = "小雅：欢迎光临夜食缘。\n（她擦了擦桌子）\n老赵: 老板，来碗面。\n小雅：今晚有炖牛腩。"
    assert _speaker_lines(reply, "小雅") == "小雅：欢迎光临夜食缘。\n小雅：今晚有炖牛腩。"
    assert _speaker_lines(reply, "老赵") == "老赵: 老板，来碗面。"
    assert _speaker_lines(reply, "不存在") == ""
    assert _speaker_lines("", "小雅") == ""
    assert _speaker_lines("没有前缀的回复", "小雅") == ""


@pytest.mark.asyncio
async def test_group_chat_records_per_character_memory(
    client, user_token, monkeypatch
) -> None:
    """群聊演出：每个角色的台词写入各自的记忆空间（按 asset_id 区分）。"""
    from app.models.asset import Asset
    from app.models.roleplay_character import RoleplayCharacter
    from app.models.user import User
    from app.providers.base import TextResult
    from app.services import sessions
    from app.services.group_service import create_group
    from app.services.provider_resolver import ResolvedTextProvider
    from sqlalchemy import select

    records: list[tuple[str, str, str, str]] = []

    def fake_record(
        user_id: str, asset_id: str, chat_id: str,
        user_msg: str, assistant_msg: str,
    ) -> None:
        records.append((asset_id, chat_id, user_msg, assistant_msg))

    monkeypatch.setattr("app.services.roleplay._record_memory_turn", fake_record)

    async with TestingSessionLocal() as db:
        u = (
            await db.execute(select(User).where(User.username == "user1"))
        ).scalar_one()
        for aid, nm in (("char-mem-1", "小雅"), ("char-mem-2", "老赵")):
            db.add(
                Asset(
                    id=aid, user_id=u.id, filename=f"{aid}.png",
                    storage_key="", storage_backend="local",
                    mime_type="image/png", size_bytes=0,
                )
            )
            db.add(
                RoleplayCharacter(
                    asset_id=aid, user_id=u.id,
                    name=nm, description="d", personality="p",
                )
            )
        chat = await sessions.create_chat(
            db, u.id, title="写歌群", character_asset_ids=["char-mem-1", "char-mem-2"],
            group=True, is_room=True,
        )
        await create_group(db, owner_id=u.id, chat_id=chat.id, name="写歌群", description="")
        await db.commit()
        chat_id = chat.id

    class _FakeProvider:
        async def generate(self, prompt: str, model: str = "", **kwargs):
            return TextResult(
                content="小雅：欢迎光临。\n老赵：老板来碗面。",
                model=model, provider="fake",
            )

    async def fake_resolver(db: object, model: str) -> ResolvedTextProvider:
        return ResolvedTextProvider(
            _FakeProvider(), "cpa", False, provider_config_id=None, source="fake"
        )

    monkeypatch.setattr("app.services.roleplay.resolve_text_provider", fake_resolver)
    r = await client.post(
        "/api/v1/roleplay/chat",
        headers={"Authorization": f"Bearer {user_token}"},
        json={
            "character_asset_ids": ["char-mem-1", "char-mem-2"],
            "session_id": chat_id,
            "group": True,
            "messages": [{"role": "user", "content": "开张了"}],
        },
    )
    assert r.status_code == 200
    # 每个角色各收到自己的台词记忆
    by_asset = {asset: msg for asset, _c, _u, msg in records}
    assert "小雅：欢迎光临。" in by_asset["char-mem-1"]
    assert "老赵：老板来碗面。" in by_asset["char-mem-2"]
    assert len(records) == 2
