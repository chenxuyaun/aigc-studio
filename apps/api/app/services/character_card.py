"""角色卡工厂：cpa 生成角色设定 + grok 生成头像 → SillyTavern V2 兼容 PNG 角色卡。

SillyTavern V2 角色卡 = PNG 头像 + tEXt 块 "chara"（base64 的 JSON，spec: chara_card_v2）。
V3 用 "ccv3" 块。解析端 V1（扁平）/V2（data 嵌套）/V3 全兼容。
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

from PIL import Image, ImageDraw, PngImagePlugin
from sqlalchemy.ext.asyncio import AsyncSession

# 解析/生成统一处理的全字段
CARD_FIELDS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "alternate_greetings",
    "system_prompt",
    "post_history_instructions",
    "creator_notes",
    "tags",
    "character_book",
    "creator",
    "character_version",
)

_CARD_SYSTEM = (
    "你是角色卡设计师。根据用户描述设计一个角色扮演角色，"
    "只输出 JSON："
    "{\"name\":\"角色名\",\"description\":\"角色外观与背景描述\","
    "\"personality\":\"性格特征\",\"scenario\":\"初始场景\","
    "\"first_mes\":\"角色开口第一句话\",\"mes_example\":\"示例对话(一行,"
    "{{user}}:/{{char}}: 格式)\","
    "\"alternate_greetings\":[\"备用开场白1\"],\"creator_notes\":\"创作备注\"}"
)

_FALLBACK_CARD = {
    "name": "新角色",
    "description": "一位神秘的角色，等待与你相遇。",
    "personality": "友善，好奇",
    "scenario": "你们在一条安静的街道上相遇。",
    "first_mes": "你好，我是这里的居民。你是谁？",
    "mes_example": "",
}


def _to_v2(card: dict[str, Any]) -> dict[str, Any]:
    """扁平字段 → V2 嵌套结构（chara 块写入格式）。"""
    return {"spec": "chara_card_v2", "spec_version": "2.0", "data": card}


def _extract_fields(source: dict[str, Any]) -> dict[str, Any]:
    """从单层 dict 提取全字段（列表/字典/字符串归一）。"""
    out: dict[str, Any] = {}
    for k in CARD_FIELDS:
        v = source.get(k)
        if k in ("alternate_greetings", "tags"):
            if isinstance(v, list):
                out[k] = [str(x) for x in v if x]
            elif isinstance(v, str) and v.strip():
                out[k] = [v]
            else:
                out[k] = []
        elif k == "character_book":
            out[k] = v if isinstance(v, dict) else {}
        elif isinstance(v, str):
            out[k] = v
        elif v is not None:
            out[k] = str(v)
    return out


def parse_character_card(data: bytes) -> dict[str, Any]:
    """解析角色卡：PNG（chara/ccv3 tEXt 块）或 JSON 字节 → 扁平全字段 dict。

    V1 扁平 JSON / V2 {spec, data:{...}} / V3 {spec: chara_card_v3, data:{...}} 全兼容。
    混合卡（顶层有字段 + data 嵌套）：顶层优先，data 补充缺失字段。
    无 name 视为无效卡，返回空 dict。
    """
    if not data:
        return {}
    raw_text: str | None = None
    # PNG：读 tEXt 块（ccv3 优先，其次 chara）
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            im = Image.open(io.BytesIO(data))
            meta = im.info.get("ccv3") or im.info.get("chara")
            if meta:
                raw_text = meta
        except Exception:
            return {}
        if not raw_text:
            return {}
    else:
        raw_text = data.decode("utf-8", errors="replace")
    # 块内容可能是 base64 的 JSON / YAML（角色卡 V1 YAML 表示）
    obj: Any = None
    if raw_text:
        import contextlib

        with contextlib.suppress(ValueError, TypeError):
            obj = json.loads(raw_text)
        if not isinstance(obj, dict):
            try:
                obj = json.loads(base64.b64decode(raw_text).decode("utf-8", errors="replace"))
            except Exception:
                obj = None
        if not isinstance(obj, dict):
            import yaml

            with contextlib.suppress(yaml.YAMLError, ValueError):
                obj = yaml.safe_load(raw_text)
    if not isinstance(obj, dict):
        return {}
    # 顶层优先，data 补充缺失
    out = _extract_fields(obj)
    if isinstance(obj.get("data"), dict):
        for k, v in _extract_fields(obj["data"]).items():
            out.setdefault(k, v)
    if not out.get("name"):
        return {}
    return out


def _pack_character_png(avatar: Image.Image, card: dict[str, Any]) -> bytes:
    """头像图 + tEXt 块 chara（V2 base64 JSON）→ PNG 字节。"""
    buf = io.BytesIO()
    chara_b64 = base64.b64encode(
        json.dumps(_to_v2(card), ensure_ascii=False).encode()
    ).decode()
    meta = PngImagePlugin.PngInfo()
    meta.add_text("chara", chara_b64)
    avatar.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


def _placeholder_png(card: dict[str, Any]) -> bytes:
    """无头像时的占位 PNG（纯色底 + 角色名首字符）。"""
    avatar = Image.new("RGB", (512, 512), (70, 80, 110))
    draw = ImageDraw.Draw(avatar)
    draw.text((16, 16), str(card.get("name", "?")[:6]), fill=(255, 255, 255))
    return _pack_character_png(avatar, card)


def export_character_card(
    png: bytes | None, card: dict[str, Any], fmt: str = "png"
) -> tuple[bytes, str]:
    """导出角色卡：png = 重打包 PNG（保证 chara 块为最新字段）；json = V2 JSON。"""
    if fmt == "json":
        return json.dumps(_to_v2(card), ensure_ascii=False, indent=2).encode(), "application/json"
    if png:
        # 重打包：读原图 + 写入最新 card 字段
        try:
            avatar = Image.open(io.BytesIO(png)).convert("RGB")
            return _pack_character_png(avatar, card), "image/png"
        except Exception:
            pass
    return _placeholder_png(card), "image/png"


def import_character_card(data: bytes) -> dict[str, Any]:
    """导入角色卡（PNG / JSON / YAML 字节）→ {card, png, source}。"""
    card = parse_character_card(data)
    if not card:
        return {}
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return {"card": card, "png": data, "source": "png"}
    head = data[:200]
    source = "yaml" if b"name:" in head or head[:1] in (b"-", b"#") else "json"
    return {"card": card, "png": _placeholder_png(card), "source": source}


async def _chat_card_json(prompt: str, max_tokens: int = 900) -> dict[str, Any] | None:
    """调 cpa 生成角色卡 JSON（带角色卡专用 system prompt，宽松解析）。"""
    import httpx
    import structlog

    from app.services import comic_service

    logger = structlog.get_logger("aigc.character_card")
    key = await comic_service._story_api_key()
    if not key:
        logger.warning("card_no_story_key")
        return None
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{comic_service.STORY_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": comic_service.STORY_MODEL,
                    "messages": [
                        {"role": "system", "content": _CARD_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                },
                timeout=120,
            )
            if r.status_code != 200:
                logger.warning("card_story_failed", status=r.status_code)
                return None
            text = str(r.json()["choices"][0]["message"]["content"] or "")
    except Exception as exc:
        logger.warning("card_story_exc", error=str(exc)[:120])
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def _build_character_json(description: str, style: str = "") -> dict[str, Any]:
    """cpa 生成角色卡 JSON；失败用模板兜底。"""
    data = await _chat_card_json(f"角色描述：{description}。风格：{style}。")
    if not isinstance(data, dict):
        return dict(_FALLBACK_CARD)
    card: dict[str, Any] = dict(_FALLBACK_CARD)
    card["alternate_greetings"] = []
    card["tags"] = []
    card["character_book"] = {}
    for k in ("name", "description", "personality", "scenario", "first_mes", "mes_example",
              "system_prompt", "post_history_instructions", "creator_notes"):
        v = str(data.get(k) or "").strip()
        if v:
            card[k] = v
    alts = data.get("alternate_greetings")
    if isinstance(alts, list):
        card["alternate_greetings"] = [str(a).strip() for a in alts if str(a).strip()]
    if not card["name"] or card["name"] == "新角色":
        m = re.search(r"[\u4e00-\u9fa5A-Za-z]{1,8}", description)
        if m:
            card["name"] = m.group(0)[:6]
    return card


async def generate_character_card(
    db: AsyncSession, description: str, style: str = ""
) -> dict[str, Any]:
    """完整流程：角色卡 JSON → 头像 → PNG → 返回（含 bytes 供调用方存资产）。"""
    card = await _build_character_json(description, style)
    # 头像：grok 文生图（竖版半身像），失败用纯色底
    avatar: Image.Image | None = None
    try:
        import httpx

        from app.services import comic_service

        key = await comic_service._grok_image_key()
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{comic_service.IMAGE_BASE}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": comic_service.IMAGE_MODEL,
                    "prompt": f"角色头像，{description}，{style}风格，竖版半身像，漫画风格",
                    "n": 1,
                },
                timeout=180,
            )
            if r.status_code == 200:
                data = await comic_service._download_result_image(client, r)
                if data:
                    avatar = Image.open(io.BytesIO(data)).convert("RGB")
                    avatar.thumbnail((512, 512))
    except Exception:
        avatar = None
    if avatar is None:
        avatar = Image.new("RGB", (512, 512), (70, 80, 110))
        draw = ImageDraw.Draw(avatar)
        draw.text((16, 16), str(card["name"])[:6], fill=(255, 255, 255))
    png = _pack_character_png(avatar, card)
    return {"card": card, "png": png, "mime": "image/png", "ext": "png"}
