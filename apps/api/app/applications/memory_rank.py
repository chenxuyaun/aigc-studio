"""长期记忆 top-k 相关性检索（方向 B）。

输入 = 用户当前消息 + 候选记忆内容列表（已按新→旧排序），
输出 = 按相关性选出的下标子集（保持原顺序）。

评分 = 0.6 × 批内相对相关性 + 0.4 × 新近度。
- 相关性用 n-gram 伪 embedding 余弦，但做**批内归一**（除以批内最大值）：
  短文本哈希余弦绝对值偏低且不稳定，相对强度才可比；
  批内全零重叠 → 退化为纯新近度（等价旧行为）。
- 空查询 → 纯新近度。
纯内存计算，无外部依赖。
"""

from __future__ import annotations

from app.applications.ngram_embed import cosine, local_embed

_W_REL = 0.6
_W_REC = 0.4


def rank_memories(query: str, contents: list[str], k: int = 12) -> list[int]:
    """返回按相关性选出的记忆下标（升序，即保持传入顺序）。

    - contents 约定已按新→旧排序（recency_norm 按位置衰减）
    - k <= 0 或空列表 → []
    - query 为空白 → 直接取前 k 个（旧行为：纯时间序）
    """
    n = len(contents)
    if k <= 0 or n == 0:
        return []
    k = min(k, n)
    if not (query or "").strip():
        return list(range(k))

    q = local_embed(query)
    rels = [cosine(q, local_embed(text or "")) for text in contents]
    mx = max(rels)
    if mx <= 1e-9:
        return list(range(k))  # 批内零重叠 → 纯新近度
    scored: list[tuple[float, int]] = []
    for i, rel in enumerate(rels):
        rec = (n - i) / n  # 第 0 条=1.0，最后一条=1/n
        scored.append((_W_REL * (rel / mx) + _W_REC * rec, i))
    scored.sort(key=lambda t: (-t[0], t[1]))
    picked = sorted(i for _, i in scored[:k])
    return picked
