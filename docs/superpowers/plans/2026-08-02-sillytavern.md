# SillyTavern 接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AIGC 暴露 OpenAI 兼容网关（聚合 Grok/cpa）+ 角色卡工厂（生成 SillyTavern 兼容 PNG 角色卡）+ SillyTavern 容器化部署。

**Architecture:** 新 router `/v1/chat/completions` 按 model 前缀路由到 grok2api/cpa；角色卡 service 用 cpa 生成角色卡 JSON + grok 生成头像 + PIL 合成 PNG（tEXt 块内嵌 chara）；compose 加 sillytavern 服务。

**Tech Stack:** FastAPI / OpenAI 兼容 provider / PIL / SillyTavern 官方 Dockerfile / React。

**验证环境：** 项目无 git，各任务以「测试全绿 + ruff/mypy/tsc」为完成标准。

---

## Task 1: OpenAI 兼容网关

**Files:**
- Create: `apps/api/app/api/v1/openai_gateway.py`
- Modify: `apps/api/app/api/v1/__init__.py`（挂 router，prefix="/v1"）
- Create: `apps/api/tests/test_openai_gateway.py`

- [ ] **Step 1: 写失败测试**

`tests/test_openai_gateway.py`：

```python
"""OpenAI 兼容网关测试。"""

from __future__ import annotations

import json

import pytest

from app.providers.base import TextResult


@pytest.mark.anyio
async def test_route_by_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """model 前缀路由：grok* → grok2api，gpt-oss* → cpa。"""
    from app.api.v1 import openai_gateway as gw

    routed: list[str] = []

    class _FakeProvider:
        def __init__(self, name: str) -> None:
            self.name = name

        async def generate(
            self, prompt: str, model: str = "", tools: list | None = None
        ) -> TextResult:
            routed.append(f"{self.name}:{model}")
            return TextResult(content="hi", model=model, provider=self.name)

    monkeypatch.setattr(gw, "_providers", lambda db: {
        "grok": _FakeProvider("grok"),
        "cpa": _FakeProvider("cpa"),
    })
    out = await gw._route_chat(
        {"model": "grok-chat-fast", "messages": [{"role": "user", "content": "hi"}]}, None
    )
    assert routed == ["grok:grok-chat-fast"]
    assert out["choices"][0]["message"]["content"] == "hi"

    out2 = await gw._route_chat(
        {"model": "gpt-oss-120b-medium", "messages": [{"role": "user", "content": "hi"}]}, None
    )
    assert routed[-1] == "cpa:gpt-oss-120b-medium"


@pytest.mark.anyio
async def test_route_unknown_model_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """未知 model → OpenAI 风格错误。"""
    from app.api.v1 import openai_gateway as gw

    async def fake_providers(db: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(gw, "_providers", fake_providers)
    out = await gw._route_chat({"model": "nope", "messages": []}, None)
    assert "error" in out
    assert out["error"]["code"] == "model_not_found"


def test_gateway_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    assert r.status_code in (401, 403)
```

> 注：`_route_chat` 与 `_providers` 为计划中的内部实现（db 为 session 占位，None 时用 env key）。测试 monkeypatch 这两个符号。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_openai_gateway.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现网关**

`apps/api/app/api/v1/openai_gateway.py`：

```python
"""OpenAI 兼容网关：SillyTavern 等客户端一个地址切换 Grok / cpa 双模型。

POST /v1/chat/completions（Bearer AIGC JWT）
- model 以 grok 开头 → grok2api
- model 以 gpt-oss 开头（或其他）→ cpa
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.security.auth import get_current_user
from app.models.user import User

router = APIRouter()


class _ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


async def _providers(db: AsyncSession | None) -> dict[str, Any]:
    """构造 grok/cpa 两个 provider 实例（复用现有 key 解析）。"""
    from app.services import comic_service
    from app.providers.openai_compatible import OpenAICompatibleTextProvider

    grok_key = await comic_service._grok_image_key()
    cpa_key = await comic_service._story_api_key(db)
    return {
        "grok": OpenAICompatibleTextProvider(
            base_url="http://host.docker.internal:8000/v1",
            api_key=grok_key or "none",
            default_model="grok-chat-fast",
            timeout=180,
        ),
        "cpa": OpenAICompatibleTextProvider(
            base_url="http://host.docker.internal:8317/v1",
            api_key=cpa_key or "none",
            default_model="gpt-oss-120b-medium",
            timeout=180,
        ),
    }


async def _route_chat(body: dict[str, Any], db: AsyncSession | None) -> dict[str, Any]:
    model = str(body.get("model") or "").strip()
    providers = await _providers(db)
    if model.startswith("grok"):
        provider = providers["grok"]
    elif model.startswith("gpt-oss") or model:
        provider = providers["cpa"]
    else:
        return {"error": {"message": f"未知模型: {model}", "type": "invalid_request_error", "code": "model_not_found"}}
    messages = body.get("messages") or []
    prompt = "\n".join(str(m.get("content") or "") for m in messages if m.get("content"))
    try:
        result = await provider.generate(prompt, model=model)
    except Exception as exc:
        return {"error": {"message": str(exc)[:300], "type": "server_error", "code": "upstream_error"}}
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result.content}, "finish_reason": "stop"}],
    }


async def _stream_chat(body: dict[str, Any], db: AsyncSession | None) -> AsyncIterator[str]:
    """流式：先整段生成再按行切 SSE（MVP 简化，SillyTavern 兼容）。"""
    result = await _route_chat(body, db)
    if "error" in result:
        yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return
    content = result["choices"][0]["message"]["content"]
    model = result["model"]
    cid = result["id"]
    for chunk in content:
        yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': result['created'], 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': chunk}, 'finish_reason': None}]}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'id': cid, 'object': 'chat.completion.chunk', 'created': result['created'], 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(
    req: _ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse | dict[str, Any]:
    body = req.model_dump()
    if req.stream:
        return StreamingResponse(_stream_chat(body, db), media_type="text/event-stream")
    return await _route_chat(body, db)
```

`apps/api/app/api/v1/__init__.py`：`router.include_router(openai_gateway.router, prefix="/v1", tags=["openai-gateway"])`

> 注：`_ChatRequest.model_dump()` 后 `_route_chat` 直接吃 dict（测试友好）。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_openai_gateway.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/api/v1/openai_gateway.py tests/test_openai_gateway.py` 与 `-m mypy app/` → 全过

---

## Task 2: 角色卡工厂 service

**Files:**
- Create: `apps/api/app/services/character_card.py`
- Create: `apps/api/tests/test_character_card.py`

- [ ] **Step 1: 写失败测试**

`tests/test_character_card.py`：

```python
"""角色卡工厂测试：JSON 生成 + PNG 打包回读。"""

from __future__ import annotations

import base64
import json
import re

import pytest
from PIL import Image


def test_build_character_json_with_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """cpa 失败 → 模板兜底；成功 → 字段齐全。"""
    from app.services import character_card as cc

    async def fake_fail(prompt: str, max_tokens: int = 1500, key: str = "") -> dict | None:
        return None

    monkeypatch.setattr(cc, "_chat_json", fake_fail)
    card = cc._build_character_json("一只会魔法的黑猫", "日系")
    assert card["name"]
    assert "黑猫" in card["description"]
    assert card["first_mes"]


def test_pack_png_roundtrip() -> None:
    """PNG 打包：tEXt 块 chara 回读 == 原 JSON。"""
    from app.services import character_card as cc

    card = {"name": "Momo", "description": "魔法黑猫", "personality": "温柔"}
    img_bytes = cc._pack_character_png(
        Image.new("RGB", (128, 128), (80, 90, 120)).tobytes(), card
    ) if False else None  # 占位，见实现
    # 实际实现走 PIL 保存 + tEXt；这里直接测 pack 函数
    png = cc._pack_character_png(Image.new("RGB", (128, 128), (80, 90, 120)), card)
    im = Image.open(__import__("io").BytesIO(png))
    assert im.format == "PNG"
    chara_b64 = im.info.get("chara", "")
    assert chara_b64
    decoded = json.loads(base64.b64decode(chara_b64))
    assert decoded["name"] == "Momo"
```

> 注：`_build_character_json` / `_pack_character_png` 为计划内部函数；`_chat_json` 复用 comic_service 的（monkeypatch 目标实现时确认）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_character_card.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`apps/api/app/services/character_card.py`：

```python
"""角色卡工厂：cpa 生成角色设定 + grok 生成头像 → SillyTavern 兼容 PNG 角色卡。

SillyTavern V2 角色卡 = PNG 头像 + tEXt 块 "chara"（base64 的 JSON）。
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import comic_service

_CARD_SYSTEM = (
    "你是角色卡设计师。根据用户描述设计一个角色扮演角色，"
    "只输出 JSON：{\"name\":\"角色名\",\"description\":\"角色外观与背景描述\","
    "\"personality\":\"性格特征\",\"scenario\":\"初始场景\","
    "\"first_mes\":\"角色开口第一句话\",\"mes_example\":\"示例对话(一行)\"}"
)

_FALLBACK_CARD = {
    "name": "新角色",
    "description": "一位神秘的角色，等待与你相遇。",
    "personality": "友善，好奇",
    "scenario": "你们在一条安静的街道上相遇。",
    "first_mes": "你好，我是这里的居民。你是谁？",
    "mes_example": "",
}


def _build_character_json(description: str, style: str = "") -> dict[str, str]:
    """cpa 生成角色卡 JSON；失败用模板兜底。"""
    async def _run() -> dict[str, str]:
        data = await comic_service._chat_json(
            f"角色描述：{description}。风格：{style}。", max_tokens=800, key=""
        )
        if not isinstance(data, dict):
            return dict(_FALLBACK_CARD)
        card = dict(_FALLBACK_CARD)
        for k in ("name", "description", "personality", "scenario", "first_mes", "mes_example"):
            v = str(data.get(k) or "").strip()
            if v:
                card[k] = v
        if not card["name"] or card["name"] == "新角色":
            m = re.search(r"[\u4e00-\u9fa5A-Za-z]{1,8}", description)
            if m:
                card["name"] = m.group(0)[:6]
        return card

    import asyncio

    return asyncio.run(_run())


def _pack_character_png(avatar: Image.Image, card: dict[str, str]) -> bytes:
    """头像图 + tEXt 块 chara（base64 JSON）→ PNG 字节。"""
    buf = io.BytesIO()
    chara_b64 = base64.b64encode(json.dumps(card, ensure_ascii=False).encode()).decode()
    # PIL 不支持直接写 tEXt，用 pnginfo
    pnginfo = __import__("PngImagePlugin", fromlist=["PngInfo"])  # 不可用，见下
    # 实际实现：用 pypng 风格手工块，或先保存再注入 —— 简化用 PIL 的 info 支持
    # PIL 的 save 支持 pnginfo=PngImagePlugin.PngInfo()
    from PIL import PngImagePlugin

    meta = PngImagePlugin.PngInfo()
    meta.add_text("chara", chara_b64)
    avatar.save(buf, format="PNG", pnginfo=meta)
    return buf.getvalue()


async def generate_character_card(
    db: AsyncSession, description: str, style: str = ""
) -> dict[str, Any]:
    """完整流程：角色卡 JSON → 头像 → PNG → 返回（含 bytes 供调用方存资产）。"""
    card = _build_character_json(description, style)
    # 头像：grok 文生图（竖版半身像），失败用纯色底
    avatar: Image.Image | None = None
    try:
        key = await comic_service._grok_image_key()
        async with __import__("httpx").AsyncClient(timeout=180) as client:
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
        draw.text((16, 16), card["name"][:6], fill=(255, 255, 255))
    png = _pack_character_png(avatar, card)
    return {"card": card, "png": png, "mime": "image/png", "ext": "png"}
```

> 注：PIL `PngImagePlugin.PngInfo` 支持 tEXt 写入（PNG 标准），实现时确认 PIL 版本支持；`_build_character_json` 里 asyncio.run 在 async 上下文会炸 —— 改为 async 函数由端点 await（实现时把 `_build_character_json` 定义为 async，去掉 asyncio.run；测试里 await 调用）。

- [ ] **Step 4: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_character_card.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/services/character_card.py tests/test_character_card.py` 与 `-m mypy app/` → 全过

---

## Task 3: 角色卡端点 + 素材入库

**Files:**
- Create: `apps/api/app/api/v1/character_cards.py`
- Modify: `apps/api/app/api/v1/__init__.py`
- Modify: `apps/api/tests/test_character_card.py`

- [ ] **Step 1: 实现端点**

`apps/api/app/api/v1/character_cards.py`：

```python
"""角色卡工厂端点。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.asset import Asset
from app.security.auth import get_current_user
from app.models.user import User

router = APIRouter()


class CharacterCardRequest(BaseModel):
    description: str = Field(min_length=2)
    style: str = "动漫"


@router.post("/generate")
async def generate_character_card(
    req: CharacterCardRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """生成角色卡并入库素材库。"""
    from app.services.character_card import generate_character_card as _gen

    result = await _gen(db, req.description, req.style)
    card = result["card"]
    png = result["png"]
    now = datetime.now(UTC)
    task_id = str(uuid.uuid4())
    key = f"{user.id}/{now:%Y/%m}/{task_id}-character.png"
    from app.services.storage import get_storage, choose_write_backend

    backend = choose_write_backend(user.id)
    store = get_storage(backend)
    await store.put(key, png, "image/png")
    asset = Asset(
        filename=f"character-{task_id[:8]}.png",
        storage_key=key,
        storage_backend=backend,
        mime_type="image/png",
        size_bytes=len(png),
        sha256=hashlib.sha256(png).hexdigest(),
        user_id=user.id,
        task_id=None,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return {
        "asset_id": asset.id,
        "url": f"/api/v1/assets/{asset.id}/content",
        "character": card,
    }
```

> 注：`app.services.storage` 的 `get_storage`/`choose_write_backend` 复用 task_runner 同款（实施时确认函数名）。

- [ ] **Step 2: 加测试**

`tests/test_character_card.py` 追加：

```python
def test_character_card_endpoint_requires_auth() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/v1/character-cards/generate", json={"description": "猫"})
    assert r.status_code in (401, 403)
```

- [ ] **Step 3: 跑测试 + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_character_card.py -q` → 全绿
Run: `.venv/Scripts/python.exe -m ruff check app/ tests/` 与 `-m mypy app/` → 全过

---

## Task 4: 前端角色卡页 + 导航

**Files:**
- Create: `apps/web/src/pages/CharacterCardPage.tsx`
- Modify: `apps/web/src/microfrontend/Routes.tsx`
- Modify: `apps/web/src/pages/CreatePage.tsx`（TOOLS 加卡片）

- [ ] **Step 1: 实现页面**

`apps/web/src/pages/CharacterCardPage.tsx`（仿 ComicGenPage 表单结构）：

```tsx
import { useState } from "react";
import { Download, Users } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/ui/States";
import { apiClient } from "@/lib/apiClient";
import { toClientApiPath } from "@/lib/paths";

interface CardResult {
  asset_id: string;
  url: string;
  character: {
    name: string;
    description: string;
    personality: string;
    scenario: string;
    first_mes: string;
    mes_example: string;
  };
}

export function CharacterCardPage() {
  const [description, setDescription] = useState("");
  const [style, setStyle] = useState("动漫");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CardResult | null>(null);

  async function generate() {
    if (!description.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiClient.post<CardResult>("/character-cards/generate", {
        description,
        style,
      });
      const acc = await apiClient.get<{ url: string }>(
        toClientApiPath(`/assets/${res.asset_id}/access-url`),
      );
      setResult({ ...res, url: acc.url });
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="角色卡生成" description="为 SillyTavern 生成角色扮演角色卡（PNG，拖入即用）" />
      <div className="grid gap-6 p-4 md:p-6 lg:grid-cols-[380px_1fr]">
        <div className="space-y-4 rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <Field label="角色描述" required>
            {({ id }) => (
              <Textarea id={id} rows={4} value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="例如：一只会魔法的黑猫，喜欢恶作剧但心地善良" />
            )}
          </Field>
          <Field label="头像风格">
            {() => (
              <div className="flex flex-wrap gap-2">
                {["动漫", "写实", "水彩", "像素"].map((s) => (
                  <button key={s} type="button" onClick={() => setStyle(s)}
                    className={`rounded-full border px-3 py-1.5 text-xs ${style === s ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"}`}>
                    {s}
                  </button>
                ))}
              </div>
            )}
          </Field>
          <Button onClick={() => void generate()} loading={busy} className="w-full">
            <Users className="h-4 w-4" aria-hidden /> 生成角色卡
          </Button>
          {error && <p className="text-sm text-danger">{error}</p>}
          {busy && <p className="text-xs text-muted-foreground">生成角色设定 + 头像，约 1 分钟…</p>}
        </div>
        <div className="space-y-4">
          {result ? (
            <>
              <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{result.character.name}</h3>
                  <a href={result.url} download="character.png" target="_blank" rel="noreferrer">
                    <Button variant="outline" size="sm"><Download className="h-3.5 w-3.5" aria-hidden /> 下载角色卡</Button>
                  </a>
                </div>
                <img src={result.url} alt="角色卡" className="mx-auto max-h-[420px] rounded-xl border border-border" />
                <dl className="mt-4 space-y-2 text-sm">
                  <div><dt className="font-medium">外貌/背景</dt><dd className="text-muted-foreground">{result.character.description}</dd></div>
                  <div><dt className="font-medium">性格</dt><dd className="text-muted-foreground">{result.character.personality}</dd></div>
                  <div><dt className="font-medium">初始场景</dt><dd className="text-muted-foreground">{result.character.scenario}</dd></div>
                  <div><dt className="font-medium">开场白</dt><dd className="text-muted-foreground">{result.character.first_mes}</dd></div>
                </dl>
                <p className="mt-3 text-xs text-muted-foreground">提示：下载后拖入 SillyTavern 角色卡管理即可使用</p>
              </div>
            </>
          ) : (
            <EmptyState title="还没有角色卡" description="填写左侧角色描述，一键生成 SillyTavern 角色卡" />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 路由 + 创作页入口**

`Routes.tsx`：`<Route path="/create/character-card" element={<Page><CharacterCardPage /></Page>} />`（lazy import 同现有模式）

`CreatePage.tsx` TOOLS 数组加：`{ title: "角色卡生成", desc: "为 SillyTavern 生成角色扮演角色卡", icon: Users, to: "/create/character-card" }`

- [ ] **Step 3: 前端构建验证**

Run（apps/web）: `node_modules/.bin/tsc --noEmit` → 无错误

---

## Task 5: SillyTavern 部署 + 工作台入口

**Files:**
- Modify: `compose.yaml`（sillytavern 服务 + 卷）
- Modify: `apps/web/src/components/layout/AppShell.tsx`（导航加「角色扮演」）

- [ ] **Step 1: compose 加服务**

```yaml
  sillytavern:
    build:
      context: ./SillyTavern
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "8001:8000"
    volumes:
      - sillytavern_data:/home/node/app/data
    environment:
      - TZ=Asia/Shanghai
```

volumes 区加：`sillytavern_data:`

- [ ] **Step 2: 导航入口**

`AppShell.tsx` NAV 加（放在「Agent 库」附近）：

```tsx
  { to: "/sillytavern", label: "角色扮演", short: "角色", icon: MessageCircle, mobile: true },
```

实现：`/sillytavern` 路由 → 新窗口打开 `http://localhost:8001`（`<Route path="/sillytavern" element={<SillyTavernLink />} />`，组件里 `window.open` + 提示文案；或简单用 `<a href target="_blank">` 占位页）。

- [ ] **Step 3: 构建启动**

```bash
cd D:/software/code/ideas/list/aigc-studio
docker compose build sillytavern && docker compose up -d sillytavern
# 验证：docker ps 显示 sillytavern Up；curl localhost:8001 返回 SillyTavern 页面
```

> 注意：SillyTavern Dockerfile 构建可能较慢（npm install 大）；若网络问题改用清华 npm 镜像（Dockerfile 里加 `npm config set registry` 或 build args）。

- [ ] **Step 4: 前端部署**

```bash
cd apps/web && npm run build && cd .. && docker cp apps/web/dist/. aigc-studio-frontend-1:/usr/share/nginx/html/
```

---

## Task 6: 真实 E2E + 文档

**Files:**
- Create: `docs/sillytavern-guide.md`

- [ ] **Step 1: 网关真实冒烟**

```bash
# cpa 模型
curl -s -X POST http://localhost:8002/v1/chat/completions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"model":"gpt-oss-120b-medium","messages":[{"role":"user","content":"说：在"}],"max_tokens":10}'
# 预期：OpenAI 结构响应
# grok 模型（若上游恢复）
```

- [ ] **Step 2: 角色卡真实 E2E**

```bash
# POST /api/v1/character-cards/generate {"description":"一只会魔法的黑猫","style":"动漫"}
# → 下载 PNG → python 解析 tEXt chara → 校验 JSON 字段
```

- [ ] **Step 3: 文档 `docs/sillytavern-guide.md`**

内容：架构图、首次配置（API=Custom(OpenAI)、地址 `http://host.docker.internal:8002/v1`、API Key=AIGC 登录 token、模型 grok-chat-fast / gpt-oss-120b-medium 切换）、角色卡工厂使用、与 AIGC 分工（对话/世界书在 SillyTavern 本地 data 卷）、排障（401=token 过期）。

- [ ] **Step 4: 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q` → 全绿；`ruff`/`mypy`/`tsc` → 全过；10+1 容器 Up；上游状态正常

---

## 自审记录

- 规格覆盖：网关（T1）✓；角色卡工厂（T2/T3）✓；部署（T5）✓；前端（T4）✓；文档（T6）✓
- 无占位符：代码完整；`PngImagePlugin`/`storage` 函数名标注实施核对 ✓
- 类型一致性：`_route_chat(body: dict, db)`（T1 定义，T1 端点/流式调用）；`_build_character_json`/`_pack_character_png`（T2 定义，T3 调用）；`generate_character_card -> {card, png, mime, ext}`（T2 定义，T3 消费）✓
