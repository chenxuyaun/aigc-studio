"""Experience Injector：创作时注入用户真实经历素材（长期记忆 event/emotion 类）。

映射 voice-engine-spec §12-2：voice 只注入了文风档案，事件素材未进创作 prompt。
本模块补齐——只读 ai_memory_entries（跨会话长期记忆），取最近的
事件/情绪片段，格式化成「可化用素材」块，交给 story/music/roundtable 创作链。

任何失败静默返回空串：创作主流程绝不因素材注入失败而中断。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.growth import MemoryEntry

# 只取「真实经历」类记忆（偏好/背景事实不构成可化用的经历片段）
_EXP_KINDS = ("event", "emotion")
_EXP_LABEL = {"event": "事件", "emotion": "情绪"}
_EXP_LIMIT = 3
_EXP_CHARS = 600


async def build_experience_prompt(
    db: AsyncSession,
    user_id: str,
    *,
    limit: int = _EXP_LIMIT,
    max_chars: int = _EXP_CHARS,
) -> str:
    """组装「真实经历素材」块；无素材/失败返回空串（调用方拼进创作 prompt）。"""
    try:
        rows = (
            (
                await db.execute(
                    select(MemoryEntry)
                    .where(
                        MemoryEntry.user_id == user_id,
                        MemoryEntry.kind.in_(_EXP_KINDS),
                    )
                    .order_by(MemoryEntry.updated_at.desc())
                    .limit(limit * 4)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        return ""
    if not rows:
        return ""
    lines: list[str] = []
    total = 0
    for r in rows[:limit]:
        line = f"- [{_EXP_LABEL.get(r.kind, r.kind)}] {r.content.strip()}"
        if total + len(line) > max_chars:
            if not lines:
                # 单条超长也保留截断版本（至少给一条素材，末尾加省略号）
                lines.append(line[: max(1, max_chars - 1)] + "…")
            break
        lines.append(line)
        total += len(line)
    if not lines:
        return ""
    return (
        "【你的真实经历素材（长期记忆）】以下是用户真实经历/感受过的片段，"
        "创作时可化用其中的细节与情绪（改写融合进作品，不要整段照抄；涉及隐私的内容注意模糊处理）：\n"
        + "\n".join(lines)
    )