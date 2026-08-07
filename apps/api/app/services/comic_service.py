"""漫画生成服务：分镜（文本模型）→ 逐格出图（图片模型）→ PIL 拼合。

- generate_storyboard：调 cpa 文本模型（gpt-oss-120b-medium）生成 JSON 分镜；
  JSON 解析宽松（兼容 ```json 包裹/截断），失败时按主题均匀拆分兜底。
- generate_panels：逐格出图（串行）；首格成功后，后续格以首格图为参考图走
  /v1/images/edits（grok-imagine-image-edit）保持角色形象一致，edits 失败自动
  降级纯文生图；单格最终失败用灰格占位。
- compose_comic_page：PIL 网格拼合（间距 + 边框），每格内底部绘制对白气泡
  （白底圆角矩形 + 中文文本；容器装有 fonts-noto-cjk，找不到字体则跳过不崩）。
"""

from __future__ import annotations

import base64
import glob
import io
import json
import os
import re

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("aigc.comic")

# 分镜文本模型（cpa 直连，稳定）
STORY_MODEL = "gpt-oss-120b-medium"
STORY_BASE = "http://host.docker.internal:8317/v1"
IMAGE_BASE = "http://host.docker.internal:8000/v1"
IMAGE_MODEL = "grok-imagine-image"
EDIT_MODEL = "grok-imagine-image-edit"  # 图生图：保持跨格角色一致
CONCURRENCY = 1
PANEL_GRID = {4: (2, 2), 6: (3, 2), 9: (3, 3)}
GAP = 12
BORDER = 4
MAX_PANEL_SIDE = 768
MANGA_WIDTH = 600

# 对白气泡样式
BUBBLE_FONT_SIZE = 20
BUBBLE_PAD_X = 14
BUBBLE_PAD_Y = 10
BUBBLE_MAX_LINES = 3
BUBBLE_MARGIN = 10  # 气泡距格子底部/两侧留白
_CJK_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
_font_cache: dict[int, ImageFont.FreeTypeFont | None] = {}


class ComicPanel:
    def __init__(self, index: int, scene: str, dialogue: str) -> None:
        self.index = index
        self.scene = scene
        self.dialogue = dialogue

    def to_dict(self) -> dict[str, str]:
        return {"index": str(self.index), "scene": self.scene, "dialogue": self.dialogue}


class ComicStory:
    """分镜结果：标题 + 面板列表。"""

    def __init__(self, title: str, panels: list[ComicPanel]) -> None:
        self.title = title
        self.panels = panels


def _cjk_font(size: int) -> ImageFont.FreeTypeFont | None:
    """查找可用中文字体；无字体返回 None（调用方跳过气泡，不崩溃）。"""
    if size in _font_cache:
        return _font_cache[size]
    font: ImageFont.FreeTypeFont | None = None
    for pat in _CJK_FONT_CANDIDATES + glob.glob("/usr/share/fonts/**/*CJK*", recursive=True):
        if not os.path.exists(pat):
            continue
        try:
            font = ImageFont.truetype(pat, size)
            break
        except Exception:
            continue
    _font_cache[size] = font
    return font


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    """按像素宽度逐字换行（中文按字）。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_width:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_speech_bubble(img: Image.Image, dialogue: str) -> None:
    """在格子内底部绘制对白气泡：白底圆角矩形 + 黑字 + 向下小尾。"""
    text = (dialogue or "").strip()
    if not text:
        return
    font = _cjk_font(BUBBLE_FONT_SIZE)
    if font is None:
        return  # 无中文字体：跳过（保证拼合不崩）
    draw = ImageDraw.Draw(img)
    max_w = img.width - 2 * (BUBBLE_MARGIN + BUBBLE_PAD_X)
    lines = _wrap_text(draw, text, font, max_w)
    if len(lines) > BUBBLE_MAX_LINES:
        lines = [*lines[: BUBBLE_MAX_LINES - 1], lines[BUBBLE_MAX_LINES - 1][:2] + "…"]
    line_h = int(BUBBLE_FONT_SIZE * 1.3)
    bubble_w = min(
        img.width - 2 * BUBBLE_MARGIN,
        max(draw.textlength(line, font=font) for line in lines) + 2 * BUBBLE_PAD_X,
    )
    bubble_h = len(lines) * line_h + 2 * BUBBLE_PAD_Y
    x0 = (img.width - bubble_w) // 2
    y1 = img.height - BUBBLE_MARGIN
    y0 = y1 - bubble_h
    draw.rounded_rectangle(
        [x0, y0, x0 + bubble_w, y1],
        radius=12,
        fill=(255, 255, 255),
        outline=(30, 30, 34),
        width=2,
    )
    # 小尾三角（指向格子底部中央）
    cx = img.width // 2
    draw.polygon(
        [(cx - 7, y1 - 1), (cx + 7, y1 - 1), (cx, y1 + 7)],
        fill=(255, 255, 255),
        outline=(30, 30, 34),
    )
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=font)
        draw.text(
            (x0 + (bubble_w - tw) // 2, y0 + BUBBLE_PAD_Y + i * line_h),
            line,
            fill=(18, 18, 22),
            font=font,
        )


async def _story_api_key(db: AsyncSession | None = None) -> str:
    """cpa（分镜文本模型）的客户端 key：从 DB provider_configs 解密。"""
    from sqlalchemy import select

    from app.models.provider_config import ProviderConfig
    from app.security.ownership import open_secret

    session = db
    if session is None:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            return await _story_api_key(s)
    row = (
        await session.execute(select(ProviderConfig).where(ProviderConfig.name.contains("cpa")))
    ).scalar_one_or_none()
    if row and row.encrypted_api_key:
        return open_secret(row.encrypted_api_key)
    return ""


async def _grok_image_key() -> str:
    """grok2api（出图）的客户端 key：环境变量优先，fallback 读 AIGC .env。"""
    import os

    key = os.environ.get("OPENAI_COMPATIBLE_API_KEY", "")
    if key:
        return key
    root = os.environ.get("AIGC_REPO_ROOT", "")
    candidates = [f"{root}/.env" if root else "", "/app/.env"]
    for p in candidates:
        if not p or not os.path.exists(p):  # noqa: ASYNC240 - 启动期小文件读取
            continue
        with open(p, encoding="utf-8") as f:  # noqa: ASYNC230 - 启动期小文件读取
            m = re.search(r"^OPENAI_COMPATIBLE_API_KEY=(.+)$", f.read(), re.M)
        if m:
            return m.group(1).strip()
    return ""


_STORY_SYSTEM = (
    "你是漫画分镜师。只输出 JSON，不要任何解释。格式："
    '{"title":"漫画标题(简短，4-12字，贴合主题)","panels":['
    '{"scene":"画面描述(中文，可直接作为绘画提示词，含人物/动作/环境/镜头/情绪)",'
    '"dialogue":"该格对白(短，无则空字符串)"}]}'
)


async def _chat_json(
    prompt: str, max_tokens: int = 1500, key: str = ""
) -> dict[str, object] | None:
    """调 cpa 文本模型，宽松解析 JSON 响应。"""
    if not key:
        key = await _story_api_key()
    if not key:
        logger.warning("comic_no_story_key")
        return None
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{STORY_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": STORY_MODEL,
                "messages": [
                    {"role": "system", "content": _STORY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
            },
            timeout=120,
        )
        if r.status_code != 200:
            logger.warning("comic_story_failed", status=r.status_code)
            return None
        text = r.json()["choices"][0]["message"]["content"]
    # 宽松解析：剥离 ```json 包裹，取第一个 { ... } 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{") : text.rfind("}") + 1]
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        logger.warning("comic_story_json_invalid", preview=raw[:120])
        return None


async def generate_storyboard(
    prompt: str, panels: int, style: str, characters: str, key: str
) -> ComicStory:
    """生成分镜（含标题）；失败时按主题拆句兜底。"""
    chars_line = f"角色设定：{characters}。" if characters.strip() else ""
    user_prompt = (
        f"漫画主题：{prompt}。风格：{style}。共 {panels} 格。{chars_line}"
        f"请设计完整起承转合的分镜，每格画面描述要具体到可直接绘画。"
    )
    data = await _chat_json(user_prompt, key=key)
    panels_raw = data.get("panels") if data else None
    title = str((data or {}).get("title") or "").strip() if isinstance(data, dict) else ""
    if not title:
        title = prompt.strip()[:20]
    if isinstance(panels_raw, list):
        items = [p for p in panels_raw if isinstance(p, dict) and p.get("scene")]
        if items:
            panels_list: list[ComicPanel] = []
            for i, it in enumerate(items[:panels]):
                panels_list.append(
                    ComicPanel(
                        i,
                        str(it.get("scene") or "").strip(),
                        str(it.get("dialogue") or "").strip(),
                    )
                )
            # 不足格数时补兜底格
            while len(panels_list) < panels:
                panels_list.append(
                    ComicPanel(len(panels_list), f"{prompt}，第{len(panels_list) + 1}格", "")
                )
            return ComicStory(title, panels_list)

    # 兜底：按句拆分主题
    sentences = [s for s in re.split(r"[。！？!?；;]", prompt) if s.strip()]
    panels_list = []
    for i in range(panels):
        scene = sentences[i % len(sentences)] if sentences else prompt
        panels_list.append(ComicPanel(i, f"{scene}，{style}风格，漫画分镜第{i + 1}格", ""))
    return ComicStory(title, panels_list)


def _to_data_url(data: bytes) -> str:
    """JPEG 字节 → data URI（grok2api /v1/images/edits 的 image.url 输入）。"""
    return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"


VISION_MODEL = "grok-chat-fast"
_VISION_PROMPT = (
    "描述这幅漫画中主角角色的形象（外貌、服装、发型、眼睛、配饰）。"
    '只输出 JSON：{"appearance":"","clothing":"","hair":"","eyes":"","accessories":""}'
)
_VISION_FIELDS = ["appearance", "clothing", "hair", "eyes", "accessories"]


async def _describe_character(image_bytes: bytes, key: str) -> str | None:
    """chat vision 看图生成角色卡（逗号分隔文本）；失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{IMAGE_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": VISION_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": _VISION_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": _to_data_url(image_bytes)},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 400,
                },
                timeout=60,
            )
            if r.status_code != 200:
                logger.warning("comic_vision_failed", status=r.status_code)
                return None
            text = str(r.json()["choices"][0]["message"]["content"] or "")
    except Exception as exc:
        logger.warning("comic_vision_exc", error=str(exc)[:120])
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return text.strip()[:200] or None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return text.strip()[:200] or None
    parts = [str(data.get(k) or "").strip() for k in _VISION_FIELDS]
    parts = [p for p in parts if p]
    return "，".join(parts) if parts else None


async def _download_result_image(client: httpx.AsyncClient, r: httpx.Response) -> bytes | None:
    """解析图片响应（url 优先，b64_json 兜底），下载字节。"""
    item = (r.json().get("data") or [{}])[0]
    url = str(item.get("url") or "")
    if url:
        if url.startswith("http://127.0.0.1"):
            url = url.replace("http://127.0.0.1:8000", "http://host.docker.internal:8000")
        img = await client.get(url, timeout=120)
        if img.status_code == 200:
            return img.content
        return None
    b64 = item.get("b64_json")
    if isinstance(b64, str) and b64:
        try:
            return base64.b64decode(b64)
        except Exception:
            return None
    return None


async def _generate_one_panel(
    key: str,
    panel: ComicPanel,
    style: str,
    characters: str = "",
    reference: bytes | None = None,
) -> bytes | None:
    """单格出图：有参考图先走图生图（edits），失败降级纯文生图。

    characters 注入图片 prompt（弱一致性：账号池无 image_edit 能力时仍按
    文字描述保持角色；有 edit 能力时以参考图为主）。
    """
    chars_line = f"，角色设定：{characters}（所有格角色形象保持一致）" if characters.strip() else ""
    img_prompt = f"{panel.scene}，{style}风格，漫画分镜{chars_line}"
    if reference is not None:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(
                    f"{IMAGE_BASE}/images/edits",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": EDIT_MODEL,
                        "prompt": (
                            f"{img_prompt}。保持参考图中角色的形象完全一致（外貌、服装、发色）"
                        ),
                        "n": 1,
                        "image": {"url": _to_data_url(reference)},
                    },
                    timeout=180,
                )
                if r.status_code == 200:
                    data = await _download_result_image(client, r)
                    if data is not None:
                        return data
                logger.warning(
                    "comic_edit_failed",
                    index=panel.index,
                    status=r.status_code,
                    detail=str(r.text)[:120],
                )
        except Exception as exc:
            logger.warning("comic_edit_exc", index=panel.index, error=str(exc)[:120])
        # 降级：edits 不可用/失败 → 该格回退纯文生图
        logger.info("comic_panel_edit_fallback", index=panel.index)
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{IMAGE_BASE}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": IMAGE_MODEL, "prompt": img_prompt, "n": 1},
                timeout=180,
            )
            if r.status_code != 200:
                logger.warning("comic_panel_failed", index=panel.index, status=r.status_code)
                return None
            return await _download_result_image(client, r)
    except Exception as exc:
        logger.warning("comic_panel_exc", index=panel.index, error=str(exc)[:120])
        return None


async def generate_panels(
    key: str, panels: list[ComicPanel], style: str, characters: str = ""
) -> list[bytes | None]:
    """逐格出图（串行）；首格成功后以其为参考图，并用 chat vision 生成
    角色卡注入后续格 prompt（vision 失败保留用户 characters）。"""
    results: list[bytes | None] = []
    reference: bytes | None = None
    role = characters
    for p in panels:
        data = await _generate_one_panel(key, p, style, role, reference)
        if data is not None and reference is None:
            reference = data  # 首格形象自举为参考图
            card = await _describe_character(data, key)
            if card:
                role = card  # vision 角色卡优先
        results.append(data)
    return results


def _placeholder_panel(width: int, height: int, text_hint: str) -> bytes:
    """灰格占位（单格出图失败时使用）。"""
    img = Image.new("RGB", (width, height), (38, 38, 46))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(90, 90, 100), width=2)
    # 无中文字体依赖：仅画提示条（英文/数字）
    msg = f"panel failed: {text_hint[:40]}"
    draw.text((16, 16), msg, fill=(160, 160, 170))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


COVER_W, COVER_H = 768, 1024


def compose_cover_page(cover_img: bytes, title: str, subtitle: str) -> bytes:
    """竖版封面页：上部封面图 + 底部标题大字 + 副标题。"""
    page = Image.new("RGB", (COVER_W, COVER_H), (20, 20, 26))
    try:
        im = Image.open(io.BytesIO(cover_img))
        im.thumbnail((COVER_W - 48, COVER_H - 340))
        cover_rgb = im.convert("RGB")
        page.paste(cover_rgb, ((COVER_W - cover_rgb.width) // 2, 24))
    except Exception:
        pass
    draw = ImageDraw.Draw(page)
    font = _cjk_font(56)
    if font is not None and title.strip():
        lines = _wrap_text(draw, title.strip(), font, COVER_W - 64)[:2]
        y = COVER_H - 190
        for line in lines:
            tw = draw.textlength(line, font=font)
            draw.text(((COVER_W - tw) // 2, y), line, fill=(245, 245, 248), font=font)
            y += 76
    font_sub = _cjk_font(22)
    if font_sub is not None and subtitle.strip():
        sub = subtitle.strip()[:24]
        tw = draw.textlength(sub, font=font_sub)
        draw.text(
            ((COVER_W - tw) // 2, COVER_H - 84),
            sub,
            fill=(150, 150, 160),
            font=font_sub,
        )
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _compose_manga(panel_images: list[bytes | None], panels: list[ComicPanel]) -> bytes:
    """条漫：单列，统一宽度 MANGA_WIDTH，高度自适应，气泡在每格底部。"""
    loaded: list[Image.Image] = []
    for i, data in enumerate(panel_images):
        if data is None:
            im = Image.new("RGB", (MANGA_WIDTH, MANGA_WIDTH), (38, 38, 46))
        else:
            try:
                im = Image.open(io.BytesIO(data))
                im.thumbnail((MANGA_WIDTH, MANGA_WIDTH * 8))
                im = im.convert("RGB")
            except Exception:
                im = Image.new("RGB", (MANGA_WIDTH, MANGA_WIDTH), (38, 38, 46))
        if i < len(panels):
            _draw_speech_bubble(im, panels[i].dialogue)
        loaded.append(im)
    page_w = MANGA_WIDTH + 2 * GAP
    page_h = GAP + sum(im.height + GAP for im in loaded)
    page = Image.new("RGB", (page_w, page_h), (28, 28, 34))
    y = GAP
    for im in loaded:
        page.paste(im, (GAP + BORDER, y + BORDER))
        y += im.height + GAP
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def compose_comic_page(
    panel_images: list[bytes | None],
    panels: list[ComicPanel],
    n_panels: int,
    layout: str = "grid",
) -> bytes:
    """PIL 拼合：grid 网格 / manga 单列条漫，每格底部绘制对白气泡。"""
    if layout == "manga":
        return _compose_manga(panel_images, panels)
    cols, rows = PANEL_GRID.get(n_panels, (3, 3))
    loaded: list[Image.Image] = []
    for _, data in enumerate(panel_images[:n_panels]):
        if data is None:
            loaded.append(Image.new("RGB", (MAX_PANEL_SIDE, MAX_PANEL_SIDE), (38, 38, 46)))
            continue
        try:
            im = Image.open(io.BytesIO(data))
            im.thumbnail((MAX_PANEL_SIDE, MAX_PANEL_SIDE))
            loaded.append(im.convert("RGB"))
        except Exception:
            loaded.append(Image.new("RGB", (MAX_PANEL_SIDE, MAX_PANEL_SIDE), (38, 38, 46)))

    cell_w = max(im.width for im in loaded)
    cell_h = max(im.height for im in loaded)
    page_w = cols * cell_w + (cols + 1) * GAP
    page_h = rows * cell_h + (rows + 1) * GAP
    page = Image.new("RGB", (page_w, page_h), (28, 28, 34))
    for i, panel_img in enumerate(loaded):
        r, c = divmod(i, cols)
        x = GAP + c * (cell_w + GAP)
        y = GAP + r * (cell_h + GAP)
        # 对白气泡画在格子内底部（无中文字体时自动跳过）
        if i < len(panels):
            _draw_speech_bubble(panel_img, panels[i].dialogue)
        # 白边边框效果
        page.paste(panel_img, (x + BORDER, y + BORDER))
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def panels_to_json(panels: list[ComicPanel]) -> str:
    return json.dumps([p.to_dict() for p in panels], ensure_ascii=False)
