# 漫画更进一步（视觉角色卡 + 封面页 + 条漫布局）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 chat vision 生成视觉角色卡实现无需 edit 账号的跨格角色一致性，新增单独封面页资产与条漫布局。

**Architecture:** 分镜模型顺带产出标题（ComicStory）；panel1 出图后用 grok-chat-fast vision 看图生成角色卡注入后续格 prompt；封面图文生图 + PIL 合成独立封面页资产；compose_comic_page 增加 manga 单列布局分支。

**Tech Stack:** Python 3.14 / FastAPI / Pillow / grok2api（chat vision + images）/ React 19 + Vite 前端。

**验证环境：** 项目无 git，各任务以「测试全绿 + ruff/mypy」为完成标准（跳过 commit 步骤）。

---

## Task 1: 实测 grok2api chat vision 格式（关键未知项）

**Files:** 无（手动 curl 验证）

- [ ] **Step 1: 用已有 panel 图实测 vision 调用**

先下载一张最近漫画任务的 panel 图（或复用 `comic_e2e_body.json` 生成的资产），构造 OpenAI 格式 vision 请求：

```bash
# 1) 取 grok2api key（AIGC .env 的 OPENAI_COMPATIBLE_API_KEY）
# 2) 下载一张 panel 图转 base64，构造请求：
python - <<'PYEOF'
import base64, json, os, subprocess
# 用一张 500KB 内的 jpg
data = base64.b64encode(open(r"D:\tmp\panel_ref.jpg", "rb").read()).decode()
payload = {
    "model": "grok-chat-fast",
    "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "描述图中角色形象，只输出 JSON"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}},
        ],
    }],
    "max_tokens": 300,
}
open(r"D:\tmp\vision_test.json", "w", encoding="utf-8").write(json.dumps(payload))
PYEOF
curl -s --max-time 60 http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $G2A_KEY" -H "Content-Type: application/json" \
  --data-binary @/d/tmp/vision_test.json | head -c 500
```

- [ ] **Step 2: 判定结果**

- 200 且返回 `choices[0].message.content`（含角色描述 JSON）→ **格式可用**，按计划实现
- 报错（如 `model_not_found` / 参数错误 / 内容被拒）→ **记录实际格式**（如 `image_url` 需 `detail` 字段、或需 `image` 顶层字段），调整 Task 3 的 payload 后继续
- 若 chat vision 完全不可用 → 把 Task 3/4 标记为「跳过，保留现有 characters 注入」，其余任务照做，并在设计文档补充说明

---

## Task 2: ComicStory + 分镜标题

**Files:**
- Modify: `apps/api/app/services/comic_service.py`（ComicPanel 后加 ComicStory；generate_storyboard 返回类型与 system prompt）
- Modify: `apps/api/tests/test_comic_service.py`（迁移现有 4 处 `generate_storyboard` 用法 + 新增 title 测试）

- [ ] **Step 1: 写失败测试（title 解析）**

在 `tests/test_comic_service.py` 加：

```python
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
    story2 = asyncio.run(comic_service.generate_storyboard("一个很长很长的漫画主题句子", 1, "日式漫画", "", key=""))
    assert story2.title  # 非空（主题截断兜底）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_comic_service.py::test_storyboard_parses_title -q`
Expected: FAIL（`ComicStory` 不存在 / `generate_storyboard` 返回 list）

- [ ] **Step 3: 实现 ComicStory 与标题解析**

`comic_service.py` ComicPanel 后加：

```python
class ComicStory:
    """分镜结果：标题 + 面板列表。"""

    def __init__(self, title: str, panels: list[ComicPanel]) -> None:
        self.title = title
        self.panels = panels
```

`generate_storyboard` 改造（system prompt 加 title；所有 return 包装 ComicStory）：

```python
_STORY_SYSTEM = (
    "你是漫画分镜师。只输出 JSON，不要任何解释。格式："
    '{"title":"漫画标题(简短，4-12字，贴合主题)","panels":['
    '{"scene":"画面描述(中文，可直接作为绘画提示词，含人物/动作/环境/镜头/情绪)",'
    '"dialogue":"该格对白(短，无则空字符串)"}]}'
)


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
            while len(panels_list) < panels:
                panels_list.append(
                    ComicPanel(len(panels_list), f"{prompt}，第{len(panels_list)+1}格", "")
                )
            return ComicStory(title, panels_list)

    sentences = [s for s in re.split(r"[。！？!?；;]", prompt) if s.strip()]
    panels_list = []
    for i in range(panels):
        scene = sentences[i % len(sentences)] if sentences else prompt
        panels_list.append(ComicPanel(i, f"{scene}，{style}风格，漫画分镜第{i+1}格", ""))
    return ComicStory(title, panels_list)
```

`_chat_json` 的 system 常量替换为 `_STORY_SYSTEM`（原来内联的字符串改为引用）。

- [ ] **Step 4: 迁移现有测试 + 跑全部**

`tests/test_comic_service.py` 中 4 处 `panels = asyncio.run(generate_storyboard(...))` 改为：

```python
story = asyncio.run(generate_storyboard(...))
panels = story.panels
```

涉及：`test_storyboard_fallback_without_key`、`test_compose_comic_page_four_panels`、`test_compose_comic_page_with_failed_panel`、`test_panels_to_json`。

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py -q`
Expected: 全绿（原 11 + 新 title 测试）
再跑：`.venv/Scripts/python.exe -m ruff check app/services/comic_service.py tests/test_comic_service.py` 与 `-m mypy app/services/comic_service.py`，全过。

---

## Task 3: `_describe_character`（chat vision 角色卡）

**Files:**
- Modify: `apps/api/app/services/comic_service.py`（常量 + 新函数）
- Modify: `apps/api/tests/test_comic_service.py`（新增测试 + fake 扩展）

- [ ] **Step 1: 写失败测试**

```python
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

        async def __aenter__(self) -> "_VisionClient":
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
    assert "橘色短毛猫" in out and "红色围巾" in out
    url, body = client.calls[0]
    assert url.endswith("/chat/completions")
    assert body["messages"][0]["content"][1]["type"] == "image_url"
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.anyio
async def test_describe_character_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """vision 500 / 非 JSON 内容 → 返回 None（触发降级）。"""
    from app.services import comic_service

    class _FailClient:
        async def __aenter__(self) -> "_FailClient":
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py::test_describe_character_json tests/test_comic_service.py::test_describe_character_failure_returns_none -q`
Expected: FAIL（`_describe_character` 不存在）

- [ ] **Step 3: 实现**

`comic_service.py` 加常量与函数（放 `_to_data_url` 之后）：

```python
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
```

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/services/comic_service.py tests/test_comic_service.py` 与 `-m mypy app/services/comic_service.py` → 全过

---

## Task 4: generate_panels 注入视觉角色卡

**Files:**
- Modify: `apps/api/app/services/comic_service.py`（generate_panels）
- Modify: `apps/api/tests/test_comic_service.py`（新增测试）

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.anyio
async def test_generate_panels_vision_card_injects(monkeypatch: pytest.MonkeyPatch) -> None:
    """首格成功后 vision 角色卡覆盖 characters 注入后续格。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(
        comic_service, "_describe_character",
        lambda img, key: _FakeAwaitable("橘色短毛猫，红色围巾，蓝色瞳孔"),
    )
    panels = [comic_service.ComicPanel(i, f"scene{i}", "") for i in range(2)]
    await comic_service.generate_panels("k", panels, "日式漫画", "用户写的角色")
    assert "橘色短毛猫" in client.calls[1][1]["prompt"]
    assert "用户写的角色" not in client.calls[1][1]["prompt"]


@pytest.mark.anyio
async def test_generate_panels_vision_fallback_keeps_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    """vision 失败时保留用户 characters 注入。"""
    from app.services import comic_service

    client = _ImageClient({})
    monkeypatch.setattr(comic_service.httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(comic_service, "_describe_character", lambda img, key: _FakeAwaitable(None))
    panels = [comic_service.ComicPanel(i, f"scene{i}", "") for i in range(2)]
    await comic_service.generate_panels("k", panels, "日式漫画", "用户写的角色")
    assert "用户写的角色" in client.calls[1][1]["prompt"]


class _FakeAwaitable:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def __await__(self):
        async def _inner() -> str | None:
            return self._value

        return _inner().__await__()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py::test_generate_panels_vision_card_injects tests/test_comic_service.py::test_generate_panels_vision_fallback_keeps_characters -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`generate_panels` 改造：

```python
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
```

- [ ] **Step 4: 跑测试 + lint**

Run: `pytest tests/test_comic_service.py -q` → 全绿；`ruff check` + `mypy` → 全过

---

## Task 5: compose_cover_page（封面页合成）

**Files:**
- Modify: `apps/api/app/services/comic_service.py`（常量 + 新函数）
- Modify: `apps/api/tests/test_comic_service.py`（新增测试）

- [ ] **Step 1: 写失败测试**

```python
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
    assert im.format == "JPEG" and im.size == (768, 1024)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py::test_compose_cover_page tests/test_comic_service.py::test_compose_cover_page_with_bad_image -q`
Expected: FAIL（`compose_cover_page` 不存在）

- [ ] **Step 3: 实现**

```python
COVER_W, COVER_H = 768, 1024


def compose_cover_page(cover_img: bytes, title: str, subtitle: str) -> bytes:
    """竖版封面页：上部封面图 + 底部标题大字 + 副标题。"""
    page = Image.new("RGB", (COVER_W, COVER_H), (20, 20, 26))
    try:
        im = Image.open(io.BytesIO(cover_img))
        im.thumbnail((COVER_W - 48, COVER_H - 340))
        im = im.convert("RGB")
        page.paste(im, ((COVER_W - im.width) // 2, 24))
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
            sub, fill=(150, 150, 160), font=font_sub,
        )
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
```

- [ ] **Step 4: 跑测试 + lint**

Run: `pytest tests/test_comic_service.py -q` → 全绿；`ruff check` + `mypy` → 全过

---

## Task 6: compose_comic_page 条漫布局

**Files:**
- Modify: `apps/api/app/services/comic_service.py`（常量 + `_compose_manga` + 签名加 layout）
- Modify: `apps/api/tests/test_comic_service.py`（新增测试）

- [ ] **Step 1: 写失败测试**

```python
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
        white = sum(
            1 for xx in range(comic_service.GAP, comic_service.GAP + 600, 12)
            if im.getpixel((xx, y + 550)) == (255, 255, 255)
        )
        if white > 10:
            found += 1
        y += 500 + comic_service.GAP
    assert found == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_comic_service.py::test_compose_comic_page_manga_layout -q`
Expected: FAIL

- [ ] **Step 3: 实现**

常量：`MANGA_WIDTH = 600`

`compose_comic_page` 签名加 layout 并在开头分派：

```python
def compose_comic_page(
    panel_images: list[bytes | None],
    panels: list[ComicPanel],
    n_panels: int,
    layout: str = "grid",
) -> bytes:
    """PIL 拼合：grid 网格 / manga 单列条漫，每格底部绘制对白气泡。"""
    if layout == "manga":
        return _compose_manga(panel_images, panels)
    ...  # 现有 grid 逻辑不变
```

新增 `_compose_manga`（放在 compose_comic_page 之前）：

```python
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
```

- [ ] **Step 4: 跑测试 + lint**

Run: `pytest tests/test_comic_service.py -q` → 全绿；`ruff check` + `mypy` → 全过

---

## Task 7: schema + task_runner 接线（title/封面/双资产/布局）

**Files:**
- Modify: `apps/api/app/schemas/generation.py`（layout 字段）
- Modify: `apps/api/app/services/task_runner.py`（_comic_real_media + 资产保存段 + result）

- [ ] **Step 1: schema 加字段**

`apps/api/app/schemas/generation.py` 的 `ComicGenerationRequest` 加：

```python
    layout: str = "grid"  # grid（网格）| manga（条漫）
```

- [ ] **Step 2: _comic_real_media 改造**

`apps/api/app/services/task_runner.py:341-390` 的 `_comic_real_media`：

```python
    from app.services.comic_service import (
        _grok_image_key,
        _story_api_key,
        compose_comic_page,
        compose_cover_page,
        generate_panels,
        generate_storyboard,
        panels_to_json,
    )

    n_panels = max(4, min(9, int(str(params.get("panels") or 4))))
    style = str(params.get("style") or "日式漫画")
    characters = str(params.get("characters") or "")
    layout = "manga" if str(params.get("layout") or "") == "manga" else "grid"
    try:
        story_key = await _story_api_key(db)
        grok_key = await _grok_image_key()
        if not story_key:
            return None, "未配置 cpa 凭据（分镜文本模型不可用）"
        if not grok_key:
            return None, "未配置 grok2api 凭据（出图模型不可用）"
        story = await generate_storyboard(prompt, n_panels, style, characters, story_key)
        panels = story.panels
        title = story.title
        panel_images = await generate_panels(grok_key, panels, style, characters)
        page_data = compose_comic_page(panel_images, panels, n_panels, layout)
        panels_info: list[dict[str, object]] = []
        for i, img in enumerate(panel_images):
            item: dict[str, object] = {
                "index": i,
                "scene": panels[i].scene,
                "dialogue": panels[i].dialogue,
            }
            if img is not None:
                item.update({"data": img, "mime": "image/jpeg", "ext": "jpg"})
            panels_info.append(item)
        # 封面：海报文生图优先，失败用首张成功 panel 兜底
        cover_img = await _generate_cover_image(grok_key, title, style, characters)
        if cover_img is None:
            for img in panel_images:
                if img is not None:
                    cover_img = img
                    break
        cover_page = (
            compose_cover_page(cover_img, title, prompt)
            if cover_img is not None
            else None
        )
        return {
            "page": (page_data, "image/jpeg", "jpg"),
            "cover": (cover_page, "image/jpeg", "jpg") if cover_page is not None else None,
            "title": title,
            "panels": panels_info,
            "storyboard": panels_to_json(panels),
        }
    except Exception as exc:
        reason = str(exc).strip()[:200] or type(exc).__name__
        logger.warning("comic_real_failed", error=reason)
        return None, reason
```

同文件（`_comic_real_media` 之前）新增 `_generate_cover_image`：

```python
async def _generate_cover_image(
    key: str, title: str, style: str, characters: str
) -> bytes | None:
    """封面海报图（文生图）；失败返回 None。"""
    from app.services import comic_service

    chars_line = f"，角色设定：{characters}" if characters.strip() else ""
    prompt = (
        f"电影海报构图，标题《{title}》，{style}风格{chars_line}，"
        "主体角色居中，戏剧化光影，高对比度"
    )
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{comic_service.IMAGE_BASE}/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": comic_service.IMAGE_MODEL,
                    "prompt": prompt,
                    "n": 1,
                },
                timeout=180,
            )
            if r.status_code != 200:
                logger.warning("comic_cover_failed", status=r.status_code)
                return None
            return await comic_service._download_result_image(client, r)
    except Exception as exc:
        logger.warning("comic_cover_exc", error=str(exc)[:120])
        return None
```

> 注：`httpx` 已在 task_runner 顶部导入（`_try_real_media` 使用）；`cast` 已导入。

- [ ] **Step 3: 资产保存段加封面资产**

`task_runner.py:509-552` 的 panel 资产循环之后（`asset = Asset(...)` 之前）插入：

```python
            # 漫画：封面页资产
            cover_asset: dict[str, object] | None = None
            if task.task_type == "comic" and isinstance(comic_result, dict):
                cover_raw = comic_result.get("cover")
                if cover_raw is not None:
                    cdata_bytes, cmime, cext = cast(tuple[bytes, str, str], cover_raw)
                    ckey = f"{task.user_id}/{now:%Y/%m}/{task_id}-cover.{cext}"
                    await store.put(ckey, cdata_bytes, cmime)
                    casset = Asset(
                        filename=f"comic-{task_id[:8]}-cover.{cext}",
                        storage_key=ckey,
                        storage_backend=backend,
                        mime_type=cmime,
                        size_bytes=len(cdata_bytes),
                        sha256=hashlib.sha256(cdata_bytes).hexdigest(),
                        user_id=task.user_id,
                        task_id=task.id,
                    )
                    db.add(casset)
                    await db.flush()
                    cover_asset = {
                        "asset_id": casset.id,
                        "url": f"/api/v1/assets/{casset.id}/content",
                    }
```

- [ ] **Step 4: result 扩展 title/cover**

`task_runner.py:589-597` 的 comic dict：

```python
                        "comic": {
                            "panels": comic_panels,
                            "assets": panel_assets,
                            "storyboard": cast(str, comic_result.get("storyboard") or "")
                            if isinstance(comic_result, dict)
                            else "",
                            "title": cast(str, comic_result.get("title") or "")
                            if isinstance(comic_result, dict)
                            else "",
                            "cover": cover_asset,
                        }
```

- [ ] **Step 5: 跑全量测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/ tests/` 与 `-m mypy app/` → 全过

---

## Task 8: 前端（布局选择器 + 封面/标题展示）

**Files:**
- Modify: `apps/web/src/pages/ComicGenPage.tsx`

- [ ] **Step 1: 加布局选择器 state 与请求字段**

`ComicGenPage.tsx`：
- 表单区（格数按钮组附近）加布局 pill 组：

```tsx
const LAYOUTS = ["grid", "manga"] as const;
// 组件内：
const [layout, setLayout] = useState<"grid" | "manga">("grid");
...
<div className="flex gap-2">
  {LAYOUTS.map((l) => (
    <button
      key={l}
      type="button"
      onClick={() => setLayout(l)}
      className={...同风格 pill，选中态同现有风格按钮...}
    >
      {l === "grid" ? "网格" : "条漫"}
    </button>
  ))}
</div>
```

- 提交 body 加 `layout`：

```tsx
      layout,
```

- [ ] **Step 2: 结果区展示标题 + 封面**

- 在「漫画页（拼合）」区块上方加标题（若 `comic.title` 存在）：

```tsx
{comic.title && <h3 className="text-lg font-bold">{comic.title}</h3>}
```

- 封面展示（`comic.cover` 存在时，位于内容页之前；url 用 access-url 换取，模式与现有 panel assets 一致）：

```tsx
{comic.cover && (
  <div>
    <h4 className="text-sm font-medium text-muted-foreground">封面</h4>
    <img src={coverUrl} alt="封面" className="mx-auto max-h-[480px] rounded-lg border" />
  </div>
)}
```

- `comic` 类型解析：`comic.cover` 与 `comic.title` 从 `task.result.comic` 读取（`CoverAsset = { asset_id, url }`）。封面 URL 的换取逻辑复用现有 panel 的 `apiClient.get('/assets/{asset_id}/access-url')` 模式（新增一个 state：`coverUrl`）。

- [ ] **Step 3: 前端构建验证**

Run（apps/web 目录）: `npm run build` 或 `npx tsc --noEmit`（按项目实际脚本，见 `apps/web/package.json`）
Expected: 无类型错误

---

## Task 9: 部署 + 真实 E2E

**Files:** 无（运维验证）

- [ ] **Step 1: 重建部署**

```bash
cd D:/software/code/ideas/list/aigc-studio
docker compose build api && docker compose up -d --force-recreate api worker
# 验证：docker ps 显示 api/worker Up (healthy)
```

- [ ] **Step 2: E2E grid 任务（4 格 + 角色设定）**

- 创建任务（body 用 UTF-8 JSON 文件，避免 curl 中文编码问题）：`{"prompt":"雨夜里橘猫侦探追捕神秘黑影","panels":4,"style":"日式漫画","characters":"红色围巾橘猫侦探","layout":"grid","model":"grok-imagine-image"}`
- 轮询至 succeeded
- 验证：
  - `result.comic.title` 非空
  - `result.comic.cover` 存在（asset_id + url）→ 下载封面页：像素验证 768x1024 + 底部标题区有亮色像素
  - `result.comic.assets` 数量 = 成功格数
  - **vision 角色卡实际可用性**：查 api 日志 `comic_vision_failed` / `comic_vision_exc` 是否出现（不出现 = vision 成功注入）
  - 内容页气泡像素验证（同之前方法）

- [ ] **Step 3: E2E manga 任务（4 格 layout=manga）**

- 同上，`"layout":"manga"`
- 验证：主资产尺寸 `width == 624`（600+2*12）、高度 > 4 格累加；逐格底部气泡白色列

- [ ] **Step 4: 前端验证**

- `http://localhost:5000` 打开漫画页：布局选择器可切换、封面图显示、标题显示、下载正常

- [ ] **Step 5: 回归**

- 跑一次普通图片任务（非 comic）确认无回归；上游状态页全绿；10 容器 Up

---

## 自审记录（写完计划后填写）

- 规格覆盖：视觉角色卡 → Task 3/4；封面页 → Task 2(title)/5(合成)/7(接线)；条漫 → Task 6/7/8；测试 → 各 Task 内置 ✓
- 无占位符 ✓（所有代码步骤含完整实现）
- 类型一致性：`ComicStory(title, panels)` 在 Task 2 定义、Task 7 消费；`compose_comic_page(..., layout)` 签名 Task 6 定义、Task 7 调用；`_describe_character(image_bytes, key) -> str | None` 一致 ✓
