"""知识库素材检索：按主题检索用户知识库文档（分块打分），供圆桌/选角等创作流程注入。

无命中返回空串——创作照常进行，不阻塞。
入库即提炼：创建文档时自动生成「精华解读」，让创作流程拿到的是"被读懂"的素材，
而非原文堆砌——落库只是开始，读懂才是目的。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.text_document import TextDocument
from app.services.knowledge_retrieval import chunk_text, retrieve

# 精华解读模板（入库时由 LLM 生成，附在文档末尾）
_SUMMARIZE_PROMPT = """你是资深的文学/文化编辑，负责把素材"读透"后写成创作可直接用的精华解读。

读透以下素材，输出 JSON（不要任何多余文字）：

{{
  "core_imagery": "核心意象（2-4 个，如：惊鸿游龙/轻云蔽月），说明其妙处",
  "core_theme": "主题与情感内核（50 字内：这篇东西到底在写什么、为什么动人）",
  "usable_points": "可当代化用的要点（2-3 条：如何把神韵移植到现代语境）",
  "forbidden": "化用禁忌（1-2 条：哪些是原文独有的、照搬即抄的东西，如原文金句/专属意象）"
}}

素材标题：{title}

素材内容：
{content}"""


from app.services.text_utils import result_text as _result_text


async def summarize_for_creation(
    db: AsyncSession,
    title: str,
    content: str,
) -> str:
    """AI 提炼素材精华解读（核心意象/主题内核/可化用点/化用禁忌）。

    返回 markdown 解读文本（追加到文档 content 使用）；任何失败返回空串（不阻塞入库）。
    """
    if not content or len(content) < 80:
        return ""
    from app.services.provider_resolver import resolve_text_provider

    prompt = _SUMMARIZE_PROMPT.format(
        title=title[:100], content=content[:4000]
    )
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.6
        )
        text = _result_text(result).strip()
        if not text or "{" not in text:
            return ""
        from app.services.text_utils import extract_json

        data = extract_json(text)
        lines = [
            "【AI 精华解读】（创作参考：先读懂再化用，禁止照搬原文金句）",
            f"- 核心意象：{data.get('core_imagery', '')}",
            f"- 主题内核：{data.get('core_theme', '')}",
            f"- 可化用要点：{data.get('usable_points', '')}",
            f"- 化用禁忌：{data.get('forbidden', '')}",
        ]
        return "\n".join(lines)
    except Exception:
        return ""


async def retrieve_theme_materials(
    db: AsyncSession,
    user_id: str,
    theme: str,
    limit: int = 3,
) -> str:
    """按主题检索用户知识库文档，返回素材摘要文本。

    命中返回「【文档标题】\n内容」拼接；无命中返回空串。
    """
    hits = await _retrieve_kb_hits(db, user_id, theme, limit)
    return "\n\n".join(f"【{title}】\n{text}" for _, title, text, _ in hits)


async def retrieve_material_titles(
    db: AsyncSession,
    user_id: str,
    theme: str,
    limit: int = 3,
) -> list[str]:
    """检索命中的文档标题列表（供前端展示「已参考」徽章）。"""
    hits = await _retrieve_kb_hits(db, user_id, theme, limit)
    return [title for _, title, _text, _score in hits]


# 联网搜索结果「读懂」提示词：与知识库入库同理——先提炼成创作可用的要点，而非原文堆砌
_WEB_DIGEST_PROMPT = """你是资深编辑。以下是按主题「{theme}」联网检索到的网页资料（可能有噪音、广告、无关内容）。
提炼出其中真正与主题相关、有创作价值的内容，输出 JSON（不要任何多余文字）：
{{
  "notes": "提炼后的素材要点（3-5 条，每条一句话：真实细节/事实/意象/说法，末尾括注来源名）"
}}
规则：
1. 宁缺毋滥，与主题无关的直接丢弃
2. **对象身份剥离**：若主题未点名具体对象（如「歌颂您」「写一个人」），而素材指向具体
   人物/事件——提炼时剥离其身份标签，只保留可用的生活细节/场景/意象语料；
   素材不得把主题窄化为素材里出现的具体人物或事件
3. 保留有用的具体细节（数字、地名、行业细节、真实说法）；不要照搬整段网页原文
原始资料：
{items}"""


async def _digest_web_results(db: AsyncSession, theme: str, items: list[dict[str, str]]) -> str:
    """搜索结果先经 AI 提炼要点（读懂后注入），失败则原样截断拼接兜底（不阻塞）。"""
    if not items:
        return ""
    blocks = "\n".join(
        f"[{i['title']}]({i['url']}): {i['content'][:300]}" for i in items
    )
    from app.services.provider_resolver import resolve_text_provider

    prompt = _WEB_DIGEST_PROMPT.format(theme=theme[:80], items=blocks[:5000])
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.4
        )
        text = _result_text(result).strip()
        from app.services.text_utils import extract_json

        data = extract_json(text)
        notes = data.get("notes") or ""
        if isinstance(notes, list):
            notes = "\n".join(f"- {n}" for n in notes if str(n).strip())
        return str(notes).strip()
    except Exception:
        # LLM 加工失败：原样拼接（截断），至少让事实可用
        return "\n".join(f"- {i['title']}：{i['content'][:120]}" for i in items)


# 创作素材检索：默认最小词元重叠（弱命中宁缺毋滥，避免稀释创作质量）
_KB_MIN_SCORE = 1


async def retrieve_kb_chunks(
    db: AsyncSession,
    user_id: str,
    doc_ids: list[str] | None = None,
    limit: int = 100,
) -> list[tuple[str, str, str]]:
    """查已确认文档并分块（/ask 与创作检索共用的底层；pending 不参与）。"""
    q = select(TextDocument).where(
        TextDocument.user_id == user_id,
        TextDocument.status == "confirmed",
    )
    if doc_ids:
        q = q.where(TextDocument.id.in_(doc_ids))
    result = await db.execute(q.order_by(TextDocument.updated_at.desc()).limit(limit))
    docs = list(result.scalars().all())
    return [
        (doc.id, doc.title, text) for doc in docs for text in chunk_text(doc.content)
    ]


async def _retrieve_kb_hits(
    db: AsyncSession,
    user_id: str,
    theme: str,
    limit: int = 3,
) -> list[tuple[str, str, str, int]]:
    """按主题检索知识库，返回 [(doc_id, title, text, score), ...] 强相关命中。

    只检索已确认文档（pending=AI 自动写入待确认，确认前不参与检索，防幻觉污染）。
    """
    chunks = await retrieve_kb_chunks(db, user_id)
    if not chunks:
        return []
    return retrieve(chunks, theme, top_k=limit, min_score=_KB_MIN_SCORE)


async def _theme_search_query(db: AsyncSession, theme: str) -> str:
    """把长主题压缩成核心检索词（20 字内），长句直搜命中差。

    保持主题开放性：只提取核心名词短语，不添加主题没有的具体对象（延续主题主权）。
    短主题（≤20 字）或 LLM 失败时原样返回——搜索链路永不因提取失败而中断。
    """
    if len(theme) <= 20 or not theme.strip():
        return theme.strip()
    from app.services.provider_resolver import resolve_text_provider

    prompt = (
        "把下面这个创作主题压缩成 1 个检索词（20 字内），用于搜索引擎查询相关资料。\n"
        "规则：提取核心名词短语；保持主题的开放性，不得添加主题没有的具体人物/对象；"
        "输出 JSON（不要任何多余文字）：{\"query\": \"检索词\"}\n\n主题："
        + theme[:200]
    )
    try:
        resolved = await resolve_text_provider(db, "")
        result = await resolved.provider.generate(  # type: ignore[attr-defined]
            prompt, resolved.model, temperature=0.2
        )
        text = _result_text(result).strip()
        from app.services.text_utils import extract_json

        try:
            query = str(extract_json(text).get("query") or "").strip()
        except Exception:
            query = ""
        if query:
            return query[:30]
    except Exception:
        pass
    return theme.strip()


def format_material_block(kb_text: str, web_text: str = "") -> str:
    """创作素材注入文案（统一「主题主权」措辞；空则不输出）。

    知识库素材（已读懂）在前，联网资料（新鲜题材）在后；两者都是语料，
    不得劫持主题方向——主题对象始终以用户主题为准。
    """
    parts: list[str] = []
    if kb_text:
        parts.append(
            "【知识库素材】（用户提供的文化/背景资料，创作必须参考并化用，禁止照搬原文；"
            "注意：主题的创作对象与方向以用户主题为准，素材只是语料，"
            "不得把主题窄化为素材中出现的具体人物/事件）\n" + kb_text
        )
    if web_text:
        parts.append(
            "【联网资料】（联网检索到的真实背景/新鲜题材，参考其中的事实与细节，禁止照搬原文；"
            "注意：素材是语料不是方向，不得劫持主题——主题对象以用户主题为准）\n" + web_text
        )
    return "\n\n".join(parts)


async def retrieve_creation_materials(
    db: AsyncSession,
    user_id: str,
    theme: str,
    limit: int = 3,
    use_web: bool = False,
) -> tuple[str, list[str], str, list[str]]:
    """创作素材统一入口：返回 (知识库文本, 知识库标题, 联网文本, 联网标题)。

    主食优先：知识库（已读懂素材）永远先注入；用户勾选联网（use_web=True）即
    显式请求网上资料 → 无条件补充搜索（新鲜题材/最新事实），搜索结果同样先经
    AI 提炼要点（读懂）再注入，排在知识库之后。
    """
    hits = await _retrieve_kb_hits(db, user_id, theme, limit)
    kb_titles = [title for _, title, _text, _score in hits]
    kb_text = "\n\n".join(f"【{title}】\n{text}" for _, title, text, _ in hits)
    web_text, web_titles = "", []
    if use_web:
        try:
            from app.services.web_search import search_web

            query = await _theme_search_query(db, theme)  # 长主题先压缩成核心检索词
            items = await search_web(query, limit=limit)
            web_text = await _digest_web_results(db, theme, items)
            web_titles = [f"🌐 {i['title'][:30]}" for i in items[:limit]]
        except Exception:
            web_text, web_titles = "", []
    return kb_text, kb_titles, web_text, web_titles
