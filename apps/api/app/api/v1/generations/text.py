import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.generation_task import GenerationTask
from app.models.text_document import TextDocument
from app.models.user import User
from app.schemas.generation import AgentChatRequest, TextGenerationRequest
from app.security.auth import get_current_user
from app.services.call_logger import log_call
from app.services.knowledge_retrieval import chunk_text, retrieve
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()

_RAG_SYSTEM_PROMPT = (
    "你是 AIGC Studio 的知识库助手。请优先基于下方【资料】回答用户问题；"
    "资料中没有答案时明确说明「资料中未找到相关信息」，不要编造。"
)


async def _build_knowledge_context(
    db: AsyncSession,
    user: User,
    doc_ids: list[str],
    question: str,
    max_chunks: int,
) -> tuple[str, list[dict[str, str]]]:
    """在指定文档内检索（仅本人文档），返回 (注入提示词, 来源列表)。"""
    if not doc_ids:
        return "", []
    docs = (
        await db.execute(
            select(TextDocument).where(
                TextDocument.user_id == user.id, TextDocument.id.in_(doc_ids)
            )
        )
    ).scalars().all()
    chunks = [(doc.id, doc.title, t) for doc in docs for t in chunk_text(doc.content)]
    hits = retrieve(chunks, question, top_k=max_chunks)
    if not hits:
        return "", []
    sections = "\n\n".join(f"【{title}】\n{text}" for _, title, text, _ in hits)
    return (
        f"{_RAG_SYSTEM_PROMPT}\n\n【资料】\n{sections}",
        [{"doc_id": doc_id, "title": title} for doc_id, title, _, _ in hits],
    )


def _sse(obj: dict[str, object]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.post("/generate", response_model=None)
async def generate_text(
    req: TextGenerationRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse | dict[str, object]:
    resolved = await resolve_text_provider(db, req.model)
    provider, model = resolved.provider, resolved.model
    prompt = req.prompt or (req.messages[-1]["content"] if req.messages else "")

    # 知识库 RAG：命中片段拼进提示词，来源随 done/响应返回
    knowledge_prompt, knowledge_sources = await _build_knowledge_context(
        db, user, req.knowledge_doc_ids or [], prompt, req.knowledge_max_chunks
    )
    if knowledge_prompt:
        prompt = f"{knowledge_prompt}\n\n【问题】\n{prompt}"

    task = GenerationTask(
        task_type="text",
        status="processing",
        model=model,
        params=json.dumps(req.model_dump()),
        user_id=user.id,
        provider_id=resolved.provider_config_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    if req.stream:

        async def stream_response() -> AsyncIterator[str]:
            full_text = ""
            error_message = ""
            started = time.monotonic()
            try:
                async for chunk in provider.stream_generate(prompt, model):  # type: ignore[attr-defined]
                    full_text += chunk
                    yield _sse({"type": "chunk", "content": chunk})
            except Exception as exc:
                # 上游失败不降级假数据：已产出的部分保留为草稿，错误原样上报
                error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
                yield _sse({"type": "error", "error": error_message})
            finally:
                task.status = "failed" if error_message else "succeeded"
                task.result = full_text
                task.model = model
                task.progress = 100
                if error_message:
                    task.error_message = error_message
                await db.commit()
                await log_call(
                    task_id=task.id,
                    task_type="text",
                    provider=resolved.source,
                    model=model,
                    status="failed" if error_message else "succeeded",
                    error_message=error_message,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    db=db,
                )
            yield _sse(
                {
                    "type": "done",
                    "task_id": task.id,
                    "error": error_message or None,
                    "model": model,
                    "source": resolved.source,
                    "is_real": True,
                    "knowledge_sources": knowledge_sources,
                }
            )

        return StreamingResponse(stream_response(), media_type="text/event-stream")

    error_message = ""
    started = time.monotonic()
    try:
        result = await provider.generate(prompt, model)  # type: ignore[attr-defined]
        content = result.content
    except Exception as exc:
        # 上游失败不降级假数据：任务标记 failed，错误原样返回
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
        content = ""
    task.status = "failed" if error_message else "succeeded"
    task.result = content
    task.model = model
    if error_message:
        task.error_message = error_message
    task.progress = 100
    await db.commit()
    await log_call(
        task_id=task.id,
        task_type="text",
        provider=resolved.source,
        model=model,
        status="failed" if error_message else "succeeded",
        error_message=error_message,
        duration_ms=int((time.monotonic() - started) * 1000),
        db=db,
    )
    return {
        "success": True,
        "data": {
            "task_id": task.id,
            "content": content,
            "error": error_message or None,
            "model": task.model,
            "source": resolved.source,
            "knowledge_sources": knowledge_sources,
        },
    }


@router.post("/agent/chat")
async def agent_chat(
    req: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """智能体对话：模型工具调用循环（SSE：tool 事件 + chunk）。"""
    from app.services.agent_chat import agent_chat_stream

    async def gen() -> AsyncIterator[str]:
        async for ev in agent_chat_stream(req.messages, req.model, db, req.tools):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
