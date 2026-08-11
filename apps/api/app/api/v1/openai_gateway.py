"""OpenAI 兼容网关：SillyTavern 等客户端一个地址切换 Grok / cpa 双模型。

POST /v1/chat/completions（Bearer AIGC JWT）
- model 以 grok 开头 → grok2api
- model 以 gpt-oss 开头（或其他）→ cpa
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.security.auth import get_current_user

router = APIRouter(prefix="/v1")

# 本地 n-gram 哈希向量维度（伪 embedding；换真实向量服务时改配置即可）
_LOCAL_EMBED_DIM = 512


def _local_embed(text: str) -> list[float]:
    """字符级 1/2-gram 特征哈希向量（中文不分词，词典外词也能命中）。

    中文连续字符取 1-gram + 2-gram；英文按单词。L2 归一化后余弦相似度
    即特征重合度。纯内存计算，供 MemoryCore 的 embedding 配置使用
    （provider=openai → 本端点；后续可替换为真实向量服务）。
    """
    vec = [0.0] * _LOCAL_EMBED_DIM
    s = text.lower()
    zh = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", s)
    grams: list[str] = re.findall(r"[a-z0-9]+", s)
    for i, ch in enumerate(zh):
        if "\u4e00" <= ch <= "\u9fff":
            grams.append(ch)
            if i + 1 < len(zh) and "\u4e00" <= zh[i + 1] <= "\u9fff":
                grams.append(zh[i : i + 2])
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16) % _LOCAL_EMBED_DIM
        vec[h] += 2.0 if len(g) >= 2 else 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class _EmbedRequest(BaseModel):
    model: str = ""
    input: str | list[str] = ""


@router.post("/embeddings")
async def embeddings(req: _EmbedRequest) -> dict[str, Any]:
    """OpenAI 兼容 embedding 端点（本地 n-gram 哈希向量，匿名可访问）。

    供 MemoryCore gateway 的 embedding.provider=openai 配置调用；
    输出格式与 OpenAI /v1/embeddings 一致。
    """
    texts = [req.input] if isinstance(req.input, str) else list(req.input)
    data = [
        {"index": i, "object": "embedding", "embedding": _local_embed(t)}
        for i, t in enumerate(texts)
    ]
    return {
        "object": "list",
        "model": req.model or "local-ngram",
        "data": data,
        "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": 0},
    }


class _ChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


async def _providers(db: AsyncSession | None) -> dict[str, Any]:
    """构造 grok/cpa 两个 provider 实例（复用现有 key 解析）。"""
    from app.providers.openai_compatible import OpenAICompatibleTextProvider
    from app.services import comic_service

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
        return {
            "error": {
                "message": f"未知模型: {model}",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        }
    messages = body.get("messages") or []
    prompt = "\n".join(str(m.get("content") or "") for m in messages if m.get("content"))
    try:
        result = await provider.generate(prompt, model=model)
    except Exception as exc:
        return {
            "error": {
                "message": str(exc)[:300],
                "type": "server_error",
                "code": "upstream_error",
            }
        }
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": "stop",
            }
        ],
    }


async def _stream_chat(body: dict[str, Any], db: AsyncSession | None) -> AsyncIterator[str]:
    """流式：整段生成后按字符切 SSE（MVP 简化，SillyTavern 兼容）。"""
    result = await _route_chat(body, db)
    if "error" in result:
        yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"
        return
    content = result["choices"][0]["message"]["content"]
    cid = result["id"]

    def _chunk(delta: dict[str, Any], finish: str | None) -> str:
        return (
            "data: "
            + json.dumps(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": result["created"],
                    "model": result["model"],
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )

    for chunk in content:
        yield _chunk({"role": "assistant", "content": chunk}, None)
    yield _chunk({}, "stop")
    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    req: _ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse | dict[str, Any]:
    body = req.model_dump()
    if req.stream:
        return StreamingResponse(_stream_chat(body, db), media_type="text/event-stream")
    return await _route_chat(body, db)
