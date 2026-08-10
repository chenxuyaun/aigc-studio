"""知识库：文档 CRUD + 基于本地检索的问答（RAG 最小版）。

文档归属当前用户；问答检索其个人文档，把命中的资料块拼进提示词后走
文本 Provider，与 /generations/text 共用回退 Mock 的兜底逻辑。
"""

from __future__ import annotations

import time
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.text_document import TextDocument
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeAskRequest,
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetail,
    KnowledgeDocumentSummary,
)
from app.security.auth import get_current_user
from app.services.call_logger import log_call
from app.services.knowledge_retrieval import chunk_text, retrieve
from app.services.provider_resolver import resolve_text_provider

router = APIRouter()

_MAX_UPLOAD_BYTES = 500_000  # 500KB，防止超大文件拖垮检索
_ALLOWED_SUFFIXES = {".txt", ".md", ".markdown"}

_SYSTEM_PROMPT = (
    "你是 AIGC Studio 的知识库助手。请优先基于下方【资料】回答用户问题；"
    "资料中没有答案时明确说明「资料中未找到相关信息」，不要编造。"
)


def _owned_or_404(doc: TextDocument | None, user: User) -> TextDocument:
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.post("/documents", response_model=KnowledgeDocumentSummary)
async def create_document(
    req: KnowledgeDocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TextDocument:
    content = req.content.strip()
    # 入库即提炼：AI 生成「精华解读」附在文档末尾（读懂素材才能用得好；失败不阻塞）
    interpretation = ""
    if len(content) >= 80:
        try:
            from app.services.knowledge_materials import summarize_for_creation

            interpretation = await summarize_for_creation(db, req.title, content)
        except Exception:
            interpretation = ""
    if interpretation:
        content = content + "\n\n" + interpretation
    doc = TextDocument(title=req.title.strip(), content=content, user_id=user.id)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.post("/upload", response_model=KnowledgeDocumentSummary)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TextDocument:
    name = file.filename or "untitled.txt"
    suffix = PurePath(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 .txt / .md / .markdown 文件")
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 500KB 限制")
    content = raw.decode("utf-8", errors="replace").strip()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")
    doc = TextDocument(title=PurePath(name).stem[:200], content=content, user_id=user.id)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/documents", response_model=list[KnowledgeDocumentSummary])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TextDocument]:
    result = await db.execute(
        select(TextDocument)
        .where(TextDocument.user_id == user.id)
        .order_by(TextDocument.updated_at.desc(), TextDocument.created_at.desc())
        .limit(200)
    )
    return list(result.scalars().all())


@router.get("/documents/{doc_id}", response_model=KnowledgeDocumentDetail)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TextDocument:
    doc = await db.get(TextDocument, doc_id)
    return _owned_or_404(doc, user)


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    doc = _owned_or_404(await db.get(TextDocument, doc_id), user)
    await db.delete(doc)
    await db.commit()
    return {"success": True}


@router.put("/documents/{doc_id}/confirm")
async def confirm_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """确认 AI 自动写入的素材（pending → confirmed）：确认后才参与创作检索。"""
    doc = _owned_or_404(await db.get(TextDocument, doc_id), user)
    doc.status = "confirmed"
    await db.commit()
    return {"success": True}


@router.post("/ask")
async def ask_knowledge(
    req: KnowledgeAskRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    question = req.question.strip()
    # 检索范围：指定 doc_ids 或全部已确认个人文档（pending 待确认不参与；与创作检索共用底层）
    from app.services.knowledge_materials import retrieve_kb_chunks

    chunks = await retrieve_kb_chunks(db, user.id, req.doc_ids)
    # AgentList 目录条目并入检索（项目/文章/对比表，作为外部选型资料）
    try:
        from app.models.agentlist import AgentArticle, AgentComparison, AgentProject

        # 按需投影（只取检索所需列，避免每请求全字段拉 2000 行）
        for proj in (
            await db.execute(
                select(
                    AgentProject.id, AgentProject.name, AgentProject.description,
                    AgentProject.categories, AgentProject.language, AgentProject.stars,
                ).limit(500)
            )
        ).all():
            chunks.append(
                (
                    f"al-proj:{proj.id}",
                    f"[AgentList] {proj.name}",
                    f"{proj.description} 分类:{proj.categories} "
                    f"语言:{proj.language} 星数:{proj.stars}",
                )
            )
        for art in (
            await db.execute(
                select(AgentArticle.id, AgentArticle.title, AgentArticle.description).limit(100)
            )
        ).all():
            chunks.append((f"al-art:{art.id}", f"[AgentList文章] {art.title}", art.description))
        for cmp_ in (
            await db.execute(
                select(
                    AgentComparison.id, AgentComparison.title, AgentComparison.description,
                ).limit(50)
            )
        ).all():
            chunks.append((f"al-cmp:{cmp_.id}", f"[AgentList对比] {cmp_.title}", cmp_.description))
    except Exception:
        pass  # 目录表缺失（旧库）时静默跳过，不影响文档问答
    hits = retrieve(chunks, question, top_k=req.max_chunks)

    if hits:
        sections = "\n\n".join(
            f"【{title}】\n{text}" for _, title, text, _ in hits
        )
        prompt = f"{_SYSTEM_PROMPT}\n\n【资料】\n{sections}\n\n【问题】\n{question}"
    else:
        # 无命中：不带资料直接答，由模型说明资料不足
        prompt = f"{_SYSTEM_PROMPT}\n（本次没有检索到相关【资料】）\n\n【问题】\n{question}"

    resolved = await resolve_text_provider(db, req.model)
    provider, model = resolved.provider, resolved.model
    error_message = ""
    started = time.monotonic()
    try:
        content = (await provider.generate(prompt, model)).content  # type: ignore[attr-defined]
    except Exception as exc:
        # 上游失败不降级假数据：错误原样上报
        error_message = f"{type(exc).__name__}: {str(exc)[:200]}"
        content = ""
    await log_call(
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
            "answer": content,
            "model": model,
            "source": resolved.source,
            "error": error_message or None,
            "sources": [
                {"doc_id": doc_id, "title": title, "snippet": text[:120]}
                for doc_id, title, text, _ in hits
            ],
        },
    }
