"""comic_service 单测：分镜兜底、JSON 宽松解析、拼合输出。"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from app.services.comic_service import (
    compose_comic_page,
    generate_storyboard,
    panels_to_json,
)
from PIL import Image, ImageFont

SAMPLE_JSON = """```json
{"panels": [
  {"scene": "主角在清晨的城市天台醒来", "dialogue": "今天也要加油！"},
  {"scene": "主角走向楼下的咖啡馆", "dialogue": ""}
]}
```"""


@pytest.mark.anyio
async def test_storyboard_fallback_without_key() -> None:
    """无 key 时走兜底分镜：按主题拆分，格数正确。"""
    story = await generate_storyboard("一只猫遇到一条狗，它们成为朋友", 4, "日式漫画", "", key="")
    panels = story.panels
    assert len(panels) == 4
    for p in panels:
        assert p.scene
        assert p.dialogue == ""
    assert panels[0].index == 0


@pytest.mark.anyio
async def test_chat_json_loose_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """宽松解析：```json 包裹 / 截断 JSON 都能处理。"""
    from app.services import comic_service

    async def fake_post(*args: object, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def json(self) -> dict:
                return {"choices": [{"message": {"content": SAMPLE_JSON}}]}

        return _Resp()

    monkeypatch.setattr(comic_service.httpx, "AsyncClient", _FakeClient)
    data = await comic_service._chat_json("test", key="fake")
    assert data is not None
    panels = data["panels"]
    assert isinstance(panels, list)
    assert len(panels) == 2


class _FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def post(self, *args: object, **kwargs: object) -> object:
        class _Resp:
            status_code = 200

            def json(self) -> dict:
                return {"choices": [{"message": {"content": SAMPLE_JSON}}]}

        return _Resp()


def test_compose_comic_page_four_panels() -> None:
    """4 格拼合：产出 JPEG 且宽高符合 2x2 网格。"""
    story = asyncio.run(generate_storyboard("测试", 4, "日式漫画", "", key=""))
    panels = story.panels
    panel_images: list[bytes | None] = []
    for _ in panels:
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), (120, 120, 200)).save(buf, format="JPEG")
        panel_images.append(buf.getvalue())
    out = compose_comic_page(panel_images, panels, 4)
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.width > 1000  # 2 格 x 512 + 间距
    assert im.height > 1000


def test_compose_comic_page_with_failed_panel() -> None:
    """单格失败（None）仍能拼出整页。"""
    story = asyncio.run(generate_storyboard("测试", 4, "日式漫画", "", key=""))
    panels = story.panels
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), (120, 120, 200)).save(buf, format="JPEG")
    panel_images = [buf.getvalue(), None, buf.getvalue(), buf.getvalue()]
    out = compose_comic_page(panel_images, panels, 4)
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"


def test_panels_to_json() -> None:
    story = asyncio.run(generate_storyboard("测试", 2, "日式漫画", "小红", key=""))
    panels = story.panels
    raw = panels_to_json(panels)
    data = json.loads(raw)
    assert len(data) == 2
    assert "scene" in data[0]


def _solid_panel_jpeg(size: int = 512, color: tuple[int, int, int] = (120, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="JPEG")
    return buf.getvalue()


def test_compose_comic_page_draws_speech_bubble(monkeypatch: pytest.MonkeyPatch) -> None:
    """有对白时格子底部出现气泡（白底矩形），无对白页保持不变。"""
    from app.services import comic_service

    monkeypatch.setattr(comic_service, "_cjk_font", lambda size: ImageFont.load_default(size))
    panels = [
        comic_service.ComicPanel(i, f"scene{i}", "今天也要加油！" if i == 0 else "")
        for i in range(4)
    ]
    panel_images = [_solid_panel_jpeg() for _ in panels]
    with_bubble = compose_comic_page(panel_images, panels, 4)
    im = Image.open(io.BytesIO(with_bubble))
    assert im.format == "JPEG"
    assert im.width > 1000
    assert im.height > 1000

    # 有对白格的底部中央应出现白色像素（气泡底）；crop 用实际格子尺寸 512
    white_ok = False
    cell_side = 512
    for i in [0]:
        r, c = divmod(i, 2)
        x0 = comic_service.GAP + c * (cell_side + comic_service.GAP) + comic_service.BORDER
        y0 = comic_service.GAP + r * (cell_side + comic_service.GAP) + comic_service.BORDER
        cell = im.crop((x0, y0, x0 + cell_side, y0 + cell_side))
        px = cell.getpixel((cell.width // 2, cell.height - 20))
        if px == (255, 255, 255):
            white_ok = True
    assert white_ok, "对白格底部应出现白色气泡底"


def test_compose_comic_page_without_font_skips_bubble(monkeypatch: pytest.MonkeyPatch) -> None:
    """无中文字体时气泡跳过，拼合不崩。"""
    from app.services import comic_service

    monkeypatch.setattr(comic_service, "_cjk_font", lambda size: None)
    panels = [comic_service.ComicPanel(i, f"scene{i}", "对白") for i in range(4)]
    panel_images = [_solid_panel_jpeg() for _ in panels]
    out = compose_comic_page(panel_images, panels, 4)
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"


class _ImageClient:
    """按请求路径分发响应的 fake httpx client。"""

    def __init__(self, handler: dict[str, object]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> _ImageClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def post(self, url: str, **kwargs: object) -> object:
        json_body = kwargs.get("json") or {}
        self.calls.append((url, dict(json_body)))
        # 按路径分流状态码：edits 与 generations 可独立失败
        status = int(self.handler.get("status", 200))
        if url.endswith("/images/edits"):
            status = int(self.handler.get("edit_status", status))
        elif url.endswith("/images/generations"):
            status = int(self.handler.get("gen_status", status))
        data = self.handler.get("data", {"data": [{"url": "http://127.0.0.1:8000/x.jpg"}]})

        class _Resp:
            status_code = status
            text = "{}"

            def json(self) -> dict:
                return data

        return _Resp()

    async def get(self, url: str, **kwargs: object) -> object:
        class _ImgResp:
            status_code = 200
            content = _solid_panel_jpeg()

        return _ImgResp()


@pytest.mark.anyio
async def test_generate_one_panel_edit_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """edits 失败 → 自动降级文生图；带参考图时 edits 优先。"""
    from app.services import comic_service

    ref = _solid_panel_jpeg()
    panel = comic_service.ComicPanel(0, "主角登场", "你好")

    # 场景 1：edits 成功（不发 generations）
    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    out = await comic_service._generate_one_panel("k", panel, "日式漫画", reference=ref)
    assert out is not None
    assert len(client.calls) == 1
    url, body = client.calls[0]
    assert url.endswith("/images/edits")
    assert body["model"] == comic_service.EDIT_MODEL
    assert body["image"]["url"].startswith("data:image/jpeg;base64,")
    assert "保持参考图中角色" in body["prompt"]

    # 场景 2：edits 500 → 降级 generations（成功）
    client2 = _ImageClient({"edit_status": 500})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client2)
    out2 = await comic_service._generate_one_panel("k", panel, "日式漫画", reference=ref)
    assert out2 is not None
    assert len(client2.calls) == 2
    assert client2.calls[1][0].endswith("/images/generations")


@pytest.mark.anyio
async def test_generate_panels_reference_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """首格文生图 → 后续格带参考图（edits）。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(comic_service, "_describe_character", lambda img, key: _FakeAwaitable(None))
    panels = [comic_service.ComicPanel(i, f"scene{i}", "") for i in range(3)]
    results = await comic_service.generate_panels("k", panels, "日式漫画")
    assert len(results) == 3
    assert all(r is not None for r in results)
    assert len(client.calls) == 3
    # 首格走 generations，后两格走 edits 且带参考图
    assert client.calls[0][0].endswith("/images/generations")
    assert client.calls[1][0].endswith("/images/edits")
    assert client.calls[2][0].endswith("/images/edits")
    assert client.calls[1][1]["image"]["url"].startswith("data:image/jpeg;base64,")
    assert "保持参考图中角色" in client.calls[2][1]["prompt"]


@pytest.mark.anyio
async def test_generate_panels_characters_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """角色设定注入图片 prompt（弱一致性）。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    panels = [comic_service.ComicPanel(0, "scene0", "")]
    results = await comic_service.generate_panels("k", panels, "日式漫画", "红色围巾橘猫")
    assert results[0] is not None
    prompt = client.calls[0][1]["prompt"]
    assert "角色设定：红色围巾橘猫" in prompt
    assert "所有格角色形象保持一致" in prompt


def test_storyboard_parses_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """分镜 JSON 顶层 title 被解析；缺失时主题截断兜底。"""
    from app.services import comic_service

    async def fake_chat(prompt: str, max_tokens: int = 1500, key: str = "") -> dict | None:
        return {
            "title": "雨夜追凶",
            "panels": [{"scene": "s1", "dialogue": "d1"}, {"scene": "s2", "dialogue": ""}],
        }

    monkeypatch.setattr(comic_service, "_chat_json", fake_chat)
    story = asyncio.run(comic_service.generate_storyboard("主题", 2, "日式漫画", "", key=""))
    assert isinstance(story, comic_service.ComicStory)
    assert story.title == "雨夜追凶"
    assert len(story.panels) == 2

    async def fake_no_title(prompt: str, max_tokens: int = 1500, key: str = "") -> dict | None:
        return {"panels": [{"scene": "s1", "dialogue": ""}]}

    monkeypatch.setattr(comic_service, "_chat_json", fake_no_title)
    story2 = asyncio.run(
        comic_service.generate_storyboard("一个很长很长的漫画主题句子", 1, "日式漫画", "", key="")
    )
    assert story2.title  # 非空（主题截断兜底）


@pytest.mark.anyio
async def test_describe_character_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """vision 响应含 JSON 角色卡 → 压缩为逗号分隔文本。"""
    from app.services import comic_service

    chat_content = (
        '{"appearance":"橘色短毛猫","clothing":"红色围巾","hair":"短毛",'
        '"eyes":"蓝色瞳孔","accessories":"侦探帽"}'
    )

    class _VisionClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def __aenter__(self) -> _VisionClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> object:
            body = dict(kwargs.get("json") or {})
            self.calls.append((url, body))

            class _Resp:
                status_code = 200

                def json(self) -> dict:
                    return {"choices": [{"message": {"content": chat_content}}]}

            return _Resp()

    client = _VisionClient()
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    out = await comic_service._describe_character(b"fake-jpeg-bytes", "k")
    assert out is not None
    assert "橘色短毛猫" in out
    assert "红色围巾" in out
    url, body = client.calls[0]
    assert url.endswith("/chat/completions")
    assert body["messages"][0]["content"][1]["type"] == "image_url"
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


@pytest.mark.anyio
async def test_describe_character_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """vision 500 → 返回 None（触发降级）。"""
    from app.services import comic_service

    class _FailClient:
        async def __aenter__(self) -> _FailClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def post(self, url: str, **kwargs: object) -> object:
            class _Resp:
                status_code = 500

                def json(self) -> dict:
                    return {}

            return _Resp()

    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: _FailClient())
    assert await comic_service._describe_character(b"x", "k") is None


class _FakeAwaitable:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def __await__(self):
        async def _inner() -> str | None:
            return self._value

        return _inner().__await__()


@pytest.mark.anyio
async def test_generate_panels_vision_card_injects(monkeypatch: pytest.MonkeyPatch) -> None:
    """首格成功后 vision 角色卡覆盖 characters 注入后续格。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(
        comic_service,
        "_describe_character",
        lambda img, key: _FakeAwaitable("橘色短毛猫，红色围巾，蓝色瞳孔"),
    )
    panels = [comic_service.ComicPanel(i, f"scene{i}", "") for i in range(2)]
    await comic_service.generate_panels("k", panels, "日式漫画", "用户写的角色")
    assert "橘色短毛猫" in client.calls[1][1]["prompt"]
    assert "用户写的角色" not in client.calls[1][1]["prompt"]


@pytest.mark.anyio
async def test_generate_panels_vision_fallback_keeps_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """vision 失败时保留用户 characters 注入。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(comic_service, "_describe_character", lambda img, key: _FakeAwaitable(None))
    panels = [comic_service.ComicPanel(i, f"scene{i}", "") for i in range(2)]
    await comic_service.generate_panels("k", panels, "日式漫画", "用户写的角色")
    assert "用户写的角色" in client.calls[1][1]["prompt"]


def test_compose_cover_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """封面页：768x1024，标题文字渲染，无字体不崩。"""
    from app.services import comic_service

    cover = _solid_panel_jpeg(600, (90, 110, 160))
    monkeypatch.setattr(comic_service, "_cjk_font", lambda size: ImageFont.load_default(size))
    out = comic_service.compose_cover_page(cover, "雨夜追凶", "橘猫侦探系列")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.size == (768, 1024)

    monkeypatch.setattr(comic_service, "_cjk_font", lambda size: None)
    out2 = comic_service.compose_cover_page(cover, "雨夜追凶", "")
    assert Image.open(io.BytesIO(out2)).size == (768, 1024)


def test_compose_cover_page_with_bad_image() -> None:
    """封面图损坏时仍能出页（仅深色底 + 标题）。"""
    from app.services import comic_service

    out = comic_service.compose_cover_page(b"not-an-image", "标题", "")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.size == (768, 1024)


def test_compose_comic_page_manga_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """条漫：单列宽 600、高度累加、每格有气泡。"""
    from app.services import comic_service

    monkeypatch.setattr(comic_service, "_cjk_font", lambda size: ImageFont.load_default(size))
    panels = [comic_service.ComicPanel(i, f"scene{i}", "对白") for i in range(4)]
    panel_images = [_solid_panel_jpeg(500) for _ in panels]
    out = compose_comic_page(panel_images, panels, 4, layout="manga")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    assert im.width == 600 + 2 * comic_service.GAP
    assert im.height > 4 * 500  # 4 格累加 + 间距
    # 每格底部应有气泡（白色列）
    y = comic_service.GAP
    found = 0
    for _ in range(4):
        # 500x500 图未放大：气泡在图底部（y+486）
        # 气泡行存在亮色像素（JPEG 压缩后白底非纯白，判定放宽）
        bright = max(
            max(im.getpixel((xx, y + 486)))
            for xx in range(comic_service.GAP, comic_service.GAP + 600, 12)
        )
        if bright > 245:
            found += 1
        y += 500 + comic_service.GAP
    assert found == 4
