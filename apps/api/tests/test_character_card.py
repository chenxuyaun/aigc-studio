"""角色卡工厂测试：JSON 生成 + PNG 打包回读。"""

from __future__ import annotations

import base64
import io
import json

import pytest
from app.services import character_card as cc
from PIL import Image, PngImagePlugin


@pytest.mark.anyio
async def test_build_character_json_with_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """cpa 失败 → 模板兜底；成功 → 字段齐全。"""
    async def fake_fail(prompt: str, max_tokens: int = 1500, key: str = "") -> dict | None:
        return None

    monkeypatch.setattr(cc, "_chat_card_json", fake_fail)
    card = await cc._build_character_json("一只会魔法的黑猫", "日系")
    assert card["name"]  # 从描述提取
    assert card["description"]  # 模板兜底
    assert card["first_mes"]

    async def fake_ok(prompt: str, max_tokens: int = 1500, key: str = "") -> dict | None:
        return {
            "name": "Momo",
            "description": "魔法黑猫",
            "personality": "温柔",
            "scenario": "咖啡馆",
            "first_mes": "要来一杯吗？",
            "mes_example": "用户：你好。Momo：喵~",
        }

    monkeypatch.setattr(cc, "_chat_card_json", fake_ok)
    card2 = await cc._build_character_json("黑猫", "")
    assert card2["name"] == "Momo"
    assert card2["first_mes"] == "要来一杯吗？"


def test_pack_png_roundtrip() -> None:
    """PNG 打包：tEXt 块 chara 回读为 V2 嵌套结构（spec + data）。"""
    card = {"name": "Momo", "description": "魔法黑猫", "personality": "温柔"}
    png = cc._pack_character_png(Image.new("RGB", (128, 128), (80, 90, 120)), card)
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG"
    chara_b64 = im.info.get("chara", "")
    assert chara_b64
    decoded = json.loads(base64.b64decode(chara_b64))
    assert decoded["spec"] == "chara_card_v2"
    assert decoded["data"]["name"] == "Momo"
    # 回读解析（顶层优先 + data 补充）
    parsed = cc.parse_character_card(png)
    assert parsed["name"] == "Momo"
    assert parsed["description"] == "魔法黑猫"


def test_parse_v2_and_v3_and_legacy() -> None:
    """V2 嵌套 / V3 ccv3 块 / V1 扁平全兼容。"""
    v2 = {"spec": "chara_card_v2", "data": {"name": "V2猫", "first_mes": "喵"}}
    assert cc.parse_character_card(json.dumps(v2).encode())["name"] == "V2猫"
    v1 = {"name": "V1猫", "description": "扁平结构"}
    assert cc.parse_character_card(json.dumps(v1).encode())["name"] == "V1猫"
    # PNG + ccv3 块（V3）
    buf = io.BytesIO()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("ccv3", base64.b64encode(json.dumps(v2, ensure_ascii=False).encode()).decode())
    Image.new("RGB", (32, 32), (10, 20, 30)).save(buf, format="PNG", pnginfo=meta)
    assert cc.parse_character_card(buf.getvalue())["name"] == "V2猫"
    # 无效输入
    assert cc.parse_character_card(b"") == {}
    assert cc.parse_character_card(json.dumps({"no": "name"}).encode()) == {}


def test_character_card_endpoint_requires_auth() -> None:
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/api/v1/character-cards/generate", json={"description": "猫"})
    assert r.status_code in (401, 403)
